import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as lambdaEventSources from 'aws-cdk-lib/aws-lambda-event-sources';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3n from 'aws-cdk-lib/aws-s3-notifications';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import { Construct } from 'constructs';
import * as path from 'path';

/**
 * Lambda Stack
 * 
 * Deploys all Lambda functions for the booking system:
 * 1. auth_resolver - AppSync authorizer for API key validation
 * 2. catalog - Service and provider management
 * 3. availability - Time slot calculation
 * 4. booking - Booking creation and management
 * 5. chat_agent - Conversational FSM agent
 */

interface LambdaStackProps extends cdk.StackProps {
  tenantsTable: dynamodb.ITable;
  apiKeysTable: dynamodb.ITable;
  servicesTable: dynamodb.ITable;
  providersTable: dynamodb.ITable;
  availabilityTable: dynamodb.ITable;
  bookingsTable: dynamodb.ITable;
  conversationsTable: dynamodb.ITable;
  categoriesTable: dynamodb.ITable;
  tenantUsageTable: dynamodb.ITable;
  workflowsTable: dynamodb.ITable;
  faqsTable: dynamodb.ITable;
  documentsTable: dynamodb.ITable;
  roomsTable: dynamodb.ITable;
  roomAssignmentsTable: dynamodb.ITable;
  userRolesTable: dynamodb.ITable;
  userPool: cdk.aws_cognito.IUserPool;
  vpc?: cdk.aws_ec2.IVpc;
  dbSecurityGroup?: cdk.aws_ec2.ISecurityGroup;
  dbSecret?: cdk.aws_secretsmanager.ISecret;
  dbEndpoint?: string; // Cluster ARN for Data API
  envName: string;
  assetsBucketName?: string;
  clientsTable: dynamodb.ITable;
  clientAuditLogsTable: dynamodb.ITable;
  dteFoliosTable: dynamodb.ITable;
  whatsappMessagesTable: dynamodb.ITable;
  whatsappNotificationTopic: cdk.aws_sns.ITopic;
  whatsappSenderQueue: cdk.aws_sqs.IQueue;
  whatsappSchedulerRoleArn?: string;
  whatsappSchedulerGroupName?: string;
  waitingListTable: dynamodb.ITable;
  waitlistPendingTable: dynamodb.ITable;
}

export class LambdaStack extends cdk.Stack {
  public readonly authResolverFunction: lambda.Function;
  public readonly catalogFunction: lambda.Function;
  public readonly availabilityFunction: lambda.Function;
  public readonly bookingFunction: lambda.Function;
  public readonly clientsFunction: lambda.Function; // New function
  public readonly chatAgentFunction: lambda.Function;
  public readonly ingestionFunction: lambda.Function;
  public readonly presignFunction: lambda.Function;
  public readonly documentsBucket: s3.Bucket;
  public readonly registerTenantFunction: lambda.Function;
  public readonly updateTenantFunction: lambda.Function;
  public readonly getTenantFunction: lambda.Function;
  public readonly metricsFunction: lambda.Function;
  public readonly workflowManagerFunction: lambda.Function;
  public readonly faqManagerFunction: lambda.Function;
  public readonly userManagementFunction: lambda.Function;
  public readonly apiKeyManagerFunction: lambda.Function;
  public readonly clientSyncFunction: lambda.Function;
  public readonly cafManagerFunction: lambda.Function;
  public readonly siiScraperFunction: lambda.Function;

  public readonly getPublicProfileFunction: lambda.Function;
  public readonly publicLinkStatusFunction: lambda.Function;
  public readonly googleIntegrationFunction: lambda.Function;
  public readonly microsoftIntegrationFunction: lambda.Function;
  public readonly checkPaymentStatusFunction: lambda.Function;
  public readonly supportManagerFunction: lambda.Function; // New function
  public readonly whatsappSenderFunction: lambda.Function;
  public readonly whatsappWebhookFunction: lambda.Function;
  public readonly twilioConnectFunction: lambda.Function;
  public readonly whatsappSchedulerFunction: lambda.Function;
  public readonly waitlistTriggerFunction: lambda.Function;
  public readonly waitlistApiFunction: lambda.Function;
  public readonly notificationSchedulerFunction: lambda.Function;

  constructor(scope: Construct, id: string, props: LambdaStackProps) {
    super(scope, id, props);

    // Force backend redeploy to pick up latest layer version - 2026-03-12 v7 (v1.1.0)
    // Get backend code path (relative to infra root, assuming cdk runs from infra)
    const backendPath = path.join(process.cwd(), '../');

    let assetsBucket: s3.IBucket | undefined;
    if (props.assetsBucketName) {
      assetsBucket = s3.Bucket.fromBucketName(this, 'ImportedAssetsBucket', props.assetsBucketName);
    }

    // Create a hash of the shared directory to force redeployments when it changes
    const crypto = require('crypto');
    const fs = require('fs');
    const sharedDir = path.join(backendPath, 'shared');
    let sharedHash = 'none';
    try {
      if (fs.existsSync(sharedDir)) {
        const hash = crypto.createHash('md5');
        const files = fs.readdirSync(sharedDir);
        files.sort().forEach((file: string) => {
          const filePath = path.join(sharedDir, file);
          if (fs.lstatSync(filePath).isFile()) {
            hash.update(file); // Include filename for better tracking
            hash.update(fs.readFileSync(filePath));
          }
        });
        sharedHash = hash.digest('hex');
      }
    } catch (e) {
      console.warn('Could not calculate shared directory hash:', e);
    }

    // Define frontend URL dynamically
    const frontendUrl = props.envName === 'prod' ? 'https://holalucia.cl' : `https://${props.envName}.holalucia.cl`;

    // Common Lambda configuration
    const commonProps = {
      runtime: lambda.Runtime.PYTHON_3_11,
      timeout: cdk.Duration.seconds(30),
      memorySize: 512,
      logRetention: logs.RetentionDays.ONE_WEEK,
      environment: {
        FRONTEND_URL: frontendUrl,
        TENANTS_TABLE: props.tenantsTable.tableName,
        API_KEYS_TABLE: props.apiKeysTable.tableName,
        SERVICES_TABLE: props.servicesTable.tableName,
        PROVIDERS_TABLE: props.providersTable.tableName,
        AVAILABILITY_TABLE: props.availabilityTable.tableName,
        BOOKINGS_TABLE: props.bookingsTable.tableName,
        CONVERSATIONS_TABLE: props.conversationsTable.tableName,
        CATEGORIES_TABLE: props.categoriesTable.tableName,
        TENANT_USAGE_TABLE: props.tenantUsageTable.tableName,
        WORKFLOWS_TABLE: props.workflowsTable.tableName,
        FAQS_TABLE: props.faqsTable.tableName,
        CLIENTS_TABLE: props.clientsTable.tableName,
        DTE_FOLIOS_TABLE: props.dteFoliosTable.tableName,
        LOG_LEVEL: 'INFO',
        // Aliases for legacy/shared code compatibility
        DYNAMODB_WORKFLOWS_TABLE: props.workflowsTable.tableName,
        DYNAMODB_FAQS_TABLE: props.faqsTable.tableName,
        ROOMS_TABLE: props.roomsTable.tableName,
        ROOM_ASSIGNMENTS_TABLE: props.roomAssignmentsTable.tableName,
        WAITING_LIST_TABLE: props.waitingListTable.tableName,
        WAITLIST_PENDING_TABLE: props.waitlistPendingTable.tableName,
        MICROSOFT_CLIENT_ID: process.env.MICROSOFT_CLIENT_ID || '',
        MICROSOFT_CLIENT_SECRET: process.env.MICROSOFT_CLIENT_SECRET || '',
        SHARED_HASH: sharedHash,
        USER_POOL_ID: props.userPool.userPoolId,
        DASHBOARD_BASE_URL: props.envName === 'prod' ? 'https://admin.holalucia.cl' : `https://control.${props.envName}.holalucia.cl`,
        ASSETS_DOMAIN: props.envName === 'prod' ? 'media.holalucia.cl' : `media.${props.envName}.holalucia.cl`,
        // SES Configuration Set para tracking de bounces/complaints (requerido para producción)
        SES_CONFIGURATION_SET: `ChatBooking-${props.envName}`,
      },
    };

    // SES Configuration Set y Email Identity — solo dev/qa
    // En prod ambos recursos existen y fueron verificados manualmente; CDK no los gestiona
    if (props.envName !== 'prod') {
      new cdk.aws_ses.CfnConfigurationSet(this, 'SesConfigurationSet', {
        name: `ChatBooking-${props.envName}`,
      });
      new cdk.aws_ses.CfnEmailIdentity(this, 'SesEmailIdentity', {
        emailIdentity: 'holalucia.ai@gmail.com',
      });
    }

    // Lambda Layer for shared code
    // Imported from SSM Parameter (updated by chat-booking-layers stack)
    const layerArn = ssm.StringParameter.valueForStringParameter(
      this, '/chatbooking/layers/python-layer-arn'
    );
    const sharedLayer = lambda.LayerVersion.fromLayerVersionArn(this, 'SharedLayer', layerArn);

    /* 
    // Commented out to use the dynamic environment-aware logic in commonProps
    const assetsDomain = ssm.StringParameter.valueForStringParameter(
      this, `/chatbooking/${props.envName}/assets-distribution-domain`
    );
    */


    // 1. Auth Resolver Lambda
    this.authResolverFunction = new lambda.Function(this, 'AuthResolverFunction', {
      ...commonProps,
      description: 'AppSync authorizer - validates API keys and returns tenant context',
      code: lambda.Code.fromAsset(path.join(backendPath, 'auth_resolver')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      timeout: cdk.Duration.seconds(10), // Fast for auth
      memorySize: 256, // Less memory for simple validation
      environment: {
        ...commonProps.environment,
        ALLOWED_IPS: process.env.ALLOWED_IPS || '181.166.197.80,191.113.67.147,191.113.66.51',
        // Rate limiting config (per API key, token bucket with DynamoDB TTL)
        TENANT_USAGE_TABLE: props.tenantUsageTable.tableName,
        RATE_LIMIT_MAX: '100',            // max requests per window
        RATE_LIMIT_WINDOW_SECONDS: '60',  // 1-minute rolling window
      },
    });

    // Grant permissions
    props.tenantsTable.grantReadData(this.authResolverFunction);
    props.apiKeysTable.grantReadWriteData(this.authResolverFunction); // WriteData for lastUsedAt update
    props.tenantUsageTable.grantReadWriteData(this.authResolverFunction); // For rate limit counters


    // 2. Catalog Lambda
    this.catalogFunction = new lambda.Function(this, 'CatalogFunction', {
      ...commonProps,
      description: 'Service and provider catalog management',
      code: lambda.Code.fromAsset(path.join(backendPath, 'catalog')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      environment: {
        ...commonProps.environment,
        ASSETS_BUCKET: props.assetsBucketName || '',
      }
    });

    // Grant permissions
    if (assetsBucket) {
      assetsBucket.grantPut(this.catalogFunction);
    }

    props.servicesTable.grantReadWriteData(this.catalogFunction);
    props.providersTable.grantReadWriteData(this.catalogFunction);
    props.categoriesTable.grantReadWriteData(this.catalogFunction);
    props.roomsTable.grantReadWriteData(this.catalogFunction);
    props.roomAssignmentsTable.grantReadWriteData(this.catalogFunction);
    props.tenantsTable.grantReadData(this.catalogFunction); // Fix: Allow LimitService to read tenant plan
    props.tenantUsageTable.grantReadWriteData(this.catalogFunction); // Fix: Allow MetricsService to increment provider count
    props.userPool.grant(this.catalogFunction, 'cognito-idp:AdminGetUser');

    // 3. Availability Lambda
    this.availabilityFunction = new lambda.Function(this, 'AvailabilityFunction', {
      ...commonProps,
      description: 'Calculate available time slots for bookings',
      code: lambda.Code.fromAsset(path.join(backendPath, 'availability')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      environment: {
        ...commonProps.environment,
        SLOT_INTERVAL_MINUTES: '15', // Default slot interval
        GOOGLE_CLIENT_ID: process.env.GOOGLE_CLIENT_ID || '',
        GOOGLE_CLIENT_SECRET: process.env.GOOGLE_CLIENT_SECRET || '',
        FORCE_DEPLOY: '2026-03-12-v7', // Force update to v1.1.0
      },
    });

    // Grant permissions
    props.availabilityTable.grantReadWriteData(this.availabilityFunction);
    props.bookingsTable.grantReadData(this.availabilityFunction); // Read for conflict detection
    props.servicesTable.grantReadData(this.availabilityFunction);
    props.providersTable.grantReadWriteData(this.availabilityFunction);
    props.tenantsTable.grantReadData(this.availabilityFunction); // Fix: Allow LimitService/Shared code to read tenant plan // Write for token refresh? Or just Read? Authenticator updates token. Read is enough if we trust refresh logic is not storing back always.
    props.userPool.grant(this.availabilityFunction, 'cognito-idp:AdminGetUser');
    // Actually, refresh_access_token operation updates the token. So we might need write if we store the new access token.
    // DynamoDBProviderIntegrationRepository.save_google_creds does write.
    // So yes, ReadWrite.

    // 4. Booking Lambda
    this.bookingFunction = new lambda.Function(this, 'BookingFunction', {
      ...commonProps,
      description: 'Booking creation, confirmation, and cancellation',
      code: lambda.Code.fromAsset(path.join(backendPath, 'booking')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      timeout: cdk.Duration.seconds(60), // More time for booking validation
      environment: {
        ...commonProps.environment,
        SES_SENDER_EMAIL: props.envName === 'prod' ? 'no-reply@mail.holalucia.cl' : 'holalucia.ai@gmail.com',
        STRIPE_SECRET_KEY: process.env.STRIPE_SECRET_KEY || '', // Passed from GitHub Secrets/Env
        GOOGLE_CLIENT_ID: process.env.GOOGLE_CLIENT_ID || '',
        GOOGLE_CLIENT_SECRET: process.env.GOOGLE_CLIENT_SECRET || '',
        WHATSAPP_NOTIFICATION_TOPIC: props.whatsappNotificationTopic.topicArn,
        RECAPTCHA_SECRET_KEY: props.envName !== 'dev' ? (process.env.RECAPTCHA_SECRET_KEY || '') : '',
      }
    });

    // Grant SES permissions
    this.bookingFunction.addToRolePolicy(new cdk.aws_iam.PolicyStatement({
      actions: ['ses:SendEmail', 'ses:SendRawEmail'],
      resources: ['*'], // In production, restrict to specific identities
    }));
    props.whatsappNotificationTopic.grantPublish(this.bookingFunction);

    // --- SQS Resilience for DTE ---
    const dteDLQ = new sqs.Queue(this, 'DteDLQ', {
      queueName: `dte-issuance-dlq-${props.envName}`,
    });

    const dteQueue = new sqs.Queue(this, 'DteQueue', {
      queueName: `dte-issuance-queue-${props.envName}`,
      visibilityTimeout: cdk.Duration.seconds(45), // Higher than the lambda timeout
      deadLetterQueue: {
        queue: dteDLQ,
        maxReceiveCount: 5,
      },
    });

    const dteWorkerFunction = new lambda.Function(this, 'DteWorkerFunction', {
      ...commonProps,
      description: 'Worker to process DTE issuance asynchronously',
      code: lambda.Code.fromAsset(path.join(backendPath, 'payment')),
      handler: 'dte_worker.lambda_handler',
      layers: [sharedLayer],
      environment: {
        ...commonProps.environment,
        DTE_API_URL: 'https://80dgp741uf.execute-api.us-east-1.amazonaws.com/dev/',
      }
    });

    // Worker triggers from SQS
    dteWorkerFunction.addEventSource(new lambdaEventSources.SqsEventSource(dteQueue, {
      batchSize: 1,
    }));

    // Permissions for Worker
    props.bookingsTable.grantReadWriteData(dteWorkerFunction);
    dteWorkerFunction.addToRolePolicy(new iam.PolicyStatement({
      actions: ['execute-api:Invoke'],
      resources: ['arn:aws:execute-api:us-east-1:607250385528:80dgp741uf/dev/*/*'],
    }));

    // --- Payment Webhook Lambda (Updated to use SQS) ---
    const paymentWebhookFunction = new lambda.Function(this, 'PaymentWebhookFunction', {
      ...commonProps,
      description: 'Generic Payment Webhook Handler',
      code: lambda.Code.fromAsset(path.join(backendPath, 'payment')),
      handler: 'webhook_handler.lambda_handler',
      layers: [sharedLayer],
      environment: {
        ...commonProps.environment,
        STRIPE_WEBHOOK_SECRET: process.env.STRIPE_WEBHOOK_SECRET || '',
        STRIPE_SECRET_KEY: process.env.STRIPE_SECRET_KEY || '',
        MP_ACCESS_TOKEN_PROD: process.env.MP_ACCESS_TOKEN_PROD || '',
        MP_WEBHOOK_SECRET: process.env.MP_WEBHOOK_SECRET || '',
        DTE_QUEUE_URL: dteQueue.queueUrl,
      }
    });

    // Permissions for Webhook to write to SQS
    dteQueue.grantSendMessages(paymentWebhookFunction);

    // Add Function URL (Public Webhook Endpoint)
    // This generates a unique HTTPS URL like https://<id>.lambda-url.<region>.on.aws/
    const webhookUrl = paymentWebhookFunction.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
    });

    // Grant permissions
    props.bookingsTable.grantReadWriteData(paymentWebhookFunction);

    // Outputs
    new cdk.CfnOutput(this, 'PaymentWebhookUrl', {
      value: webhookUrl.url,
      description: 'Webhook URL for Payment Providers',
    });

    // Grant permissions
    props.bookingsTable.grantReadWriteData(this.bookingFunction);
    props.servicesTable.grantReadData(this.bookingFunction);
    props.providersTable.grantReadData(this.bookingFunction);
    props.tenantsTable.grantReadData(this.bookingFunction);
    props.conversationsTable.grantReadData(this.bookingFunction);
    props.availabilityTable.grantReadData(this.bookingFunction); // Added permissions for Availability table
    props.roomsTable.grantReadData(this.bookingFunction);
    props.roomAssignmentsTable.grantReadData(this.bookingFunction);
    props.tenantUsageTable.grantWriteData(this.bookingFunction); // For metrics tracking
    props.providersTable.grantReadWriteData(this.bookingFunction); // For Google Integration (read/write tokens)
    props.userRolesTable.grantReadData(this.bookingFunction); // For enforce_not_readonly()
    props.userPool.grant(this.bookingFunction, 'cognito-idp:AdminGetUser');

    // 5. Chat Agent Lambda
    this.chatAgentFunction = new lambda.Function(this, 'ChatAgentFunction', {
      ...commonProps,
      description: 'Conversational FSM agent for booking flow',
      code: lambda.Code.fromAsset(path.join(backendPath, 'chat_agent')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      timeout: cdk.Duration.seconds(120), // More time for conversation logic / RAG
      memorySize: 1024, // More memory for FSM processing
      // vpc: props.vpc,
      // securityGroups: props.dbSecurityGroup ? [props.dbSecurityGroup] : undefined,
      environment: {
        ...commonProps.environment,
        // DB_SECRET_ARN: props.dbSecret?.secretArn || '',
        // DB_ENDPOINT: props.dbEndpoint || '',
        EMBEDDING_MODEL_ID: process.env.EMBEDDING_MODEL_ID || 'amazon.titan-embed-text-v2:0',
        LLM_MODEL_ID: 'amazon.titan-text-express-v1', // HARDCODED FORCE TO FIX ANTHROPIC ERROR
      }
    });

    // Grant permissions - chat agent needs access to everything
    props.conversationsTable.grantReadWriteData(this.chatAgentFunction);
    props.servicesTable.grantReadData(this.chatAgentFunction);
    props.providersTable.grantReadData(this.chatAgentFunction);
    props.availabilityTable.grantReadData(this.chatAgentFunction);
    props.bookingsTable.grantReadWriteData(this.chatAgentFunction);
    props.tenantUsageTable.grantWriteData(this.chatAgentFunction); // For metrics tracking
    props.workflowsTable.grantReadWriteData(this.chatAgentFunction); // For self-healing (create default workflow)
    props.tenantsTable.grantReadData(this.chatAgentFunction);
    props.userPool.grant(this.chatAgentFunction, 'cognito-idp:AdminGetUser');
    props.waitingListTable.grantReadWriteData(this.chatAgentFunction); // For waitlist feature

    // Grant Bedrock Access for AI Plans
    this.chatAgentFunction.addToRolePolicy(new cdk.aws_iam.PolicyStatement({
      actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
      resources: ['*'], // Scope this down in production to specific models
    }));

    // Grant RDS Data API Access - REMOVED for Cost Optimization
    /*
    if (props.dbSecret && props.dbEndpoint) {
      props.dbSecret.grantRead(this.chatAgentFunction);
      this.chatAgentFunction.addToRolePolicy(new cdk.aws_iam.PolicyStatement({
        actions: ['rds-data:ExecuteStatement', 'rds-data:BatchExecuteStatement'],
        resources: [props.dbEndpoint], // DB Cluster ARN
      }));
    }
    */

    // 6. Register Tenant Lambda
    this.registerTenantFunction = new lambda.Function(this, 'RegisterTenantFunction', {
      ...commonProps,
      description: 'Public tenant registration endpoint',
      code: lambda.Code.fromAsset(path.join(backendPath, 'register_tenant')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      environment: {
        ...commonProps.environment,
        USER_POOL_ID: props.userPool.userPoolId,
        WORKFLOWS_TABLE: props.workflowsTable.tableName,
        USER_ROLES_TABLE: props.userRolesTable.tableName,
        RECAPTCHA_SECRET_KEY: process.env.RECAPTCHA_SECRET_KEY || '',
      },
      timeout: cdk.Duration.seconds(15),
    });

    // Grant permissions
    props.tenantsTable.grantReadWriteData(this.registerTenantFunction);
    props.apiKeysTable.grantReadWriteData(this.registerTenantFunction);
    props.workflowsTable.grantReadWriteData(this.registerTenantFunction);
    props.userRolesTable.grantReadWriteData(this.registerTenantFunction);
    props.categoriesTable.grantReadWriteData(this.registerTenantFunction);
    props.userPool.grant(this.registerTenantFunction, 'cognito-idp:AdminCreateUser', 'cognito-idp:AdminSetUserPassword', 'cognito-idp:AdminGetUser');

    // 7. Update Tenant Lambda
    this.updateTenantFunction = new lambda.Function(this, 'UpdateTenantFunction', {
      ...commonProps,
      description: 'Tenant settings update',
      code: lambda.Code.fromAsset(path.join(backendPath, 'update_tenant')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      environment: {
        ...commonProps.environment,
        USER_POOL_ID: props.userPool.userPoolId,
      },
    });

    // Grant permissions
    props.tenantsTable.grantReadWriteData(this.updateTenantFunction);
    props.userPool.grant(this.updateTenantFunction, 'cognito-idp:AdminGetUser');
    props.userRolesTable.grantReadData(this.updateTenantFunction);

    // 8. Get Tenant Lambda
    this.getTenantFunction = new lambda.Function(this, 'GetTenantFunction', {
      ...commonProps,
      description: 'Get tenant details',
      code: lambda.Code.fromAsset(path.join(backendPath, 'get_tenant')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      environment: {
        ...commonProps.environment,
        USER_POOL_ID: props.userPool.userPoolId,
      },
    });

    // Grant permissions
    props.tenantsTable.grantReadData(this.getTenantFunction);
    props.userPool.grant(this.getTenantFunction, 'cognito-idp:AdminGetUser');
    props.workflowsTable.grantReadWriteData(this.getTenantFunction);  // Allowed for self-healing (default workflow creation)

    // 9. Metrics Lambda
    this.metricsFunction = new lambda.Function(this, 'MetricsFunction', {
      ...commonProps,
      description: 'Dashboard metrics and usage analytics',
      code: lambda.Code.fromAsset(path.join(backendPath, 'metrics')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      timeout: cdk.Duration.seconds(15),
      memorySize: 256,
    });

    // Grant permissions - read/write for metrics, read for related data
    props.tenantUsageTable.grantReadWriteData(this.metricsFunction);

    // 10. Workflow Manager Lambda
    this.workflowManagerFunction = new lambda.Function(this, 'WorkflowManagerFunction', {
      ...commonProps,
      description: 'Workflow CRUD operations',
      code: lambda.Code.fromAsset(path.join(backendPath, 'workflow_manager')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
    });

    // Grant permissions
    props.workflowsTable.grantReadWriteData(this.workflowManagerFunction);
    props.tenantsTable.grantReadData(this.workflowManagerFunction);
    props.userPool.grant(this.workflowManagerFunction, 'cognito-idp:AdminGetUser');

    // 11. FAQ Manager Lambda
    this.faqManagerFunction = new lambda.Function(this, 'FaqManagerFunction', {
      ...commonProps,
      description: 'FAQ CRUD operations',
      code: lambda.Code.fromAsset(path.join(backendPath, 'faq_manager')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
    });

    // Grant permissions
    props.faqsTable.grantReadWriteData(this.faqManagerFunction);
    props.tenantsTable.grantReadData(this.faqManagerFunction);
    props.userPool.grant(this.faqManagerFunction, 'cognito-idp:AdminGetUser');

    // Grant permissions to Chat Agent to read FAQs
    props.faqsTable.grantReadData(this.chatAgentFunction);

    // 12. User Management Lambda
    this.userManagementFunction = new lambda.Function(this, 'UserManagementFunction', {
      ...commonProps,
      description: 'User management operations (invite, list, update role, remove)',
      code: lambda.Code.fromAsset(path.join(backendPath, 'user_management')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      environment: {
        ...commonProps.environment,
        USER_POOL_ID: props.userPool.userPoolId,
        USER_ROLES_TABLE: props.userRolesTable.tableName,
        FROM_EMAIL: props.envName === 'prod' ? 'no-reply@mail.holalucia.cl' : 'holalucia.ai@gmail.com',
      },
    });

    // Grant Cognito permissions for user management
    props.userPool.grant(this.userManagementFunction,
      'cognito-idp:AdminCreateUser',
      'cognito-idp:AdminGetUser',
      'cognito-idp:ListUsers',
      'cognito-idp:AdminUpdateUserAttributes',
      'cognito-idp:AdminDisableUser',
      'cognito-idp:AdminResetUserPassword'
    );

    // Grant read access to tenants table for plan validation
    props.tenantsTable.grantReadData(this.userManagementFunction);

    // Grant read/write access to user roles table
    props.userRolesTable.grantReadWriteData(this.userManagementFunction);

    // Grant SES permissions for sending invitations
    this.userManagementFunction.addToRolePolicy(new cdk.aws_iam.PolicyStatement({
      actions: ['ses:SendEmail', 'ses:SendRawEmail'],
      resources: ['*'], // In production, restrict to specific identity ARNs
    }));

    // 14. API Key Manager Lambda
    this.apiKeyManagerFunction = new lambda.Function(this, 'ApiKeyManagerFunction', {
      ...commonProps,
      description: 'API Key management operations',
      code: lambda.Code.fromAsset(path.join(backendPath, 'apikey_manager')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
    });

    // Grant permissions
    props.apiKeysTable.grantReadWriteData(this.apiKeyManagerFunction);
    props.tenantsTable.grantReadData(this.apiKeyManagerFunction);
    props.userPool.grant(this.apiKeyManagerFunction, 'cognito-idp:AdminGetUser');

    // 15. Get Public Profile Lambda
    this.getPublicProfileFunction = new lambda.Function(this, 'GetPublicProfileFunction', {
      ...commonProps,
      description: 'Get public tenant profile by slug',
      code: lambda.Code.fromAsset(path.join(backendPath, 'get_public_profile')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      environment: {
        ...commonProps.environment,
      },
    });

    // Grant permissions
    props.tenantsTable.grantReadData(this.getPublicProfileFunction);
    props.servicesTable.grantReadData(this.getPublicProfileFunction);
    props.providersTable.grantReadData(this.getPublicProfileFunction);

    // 16. Support Manager Lambda
    this.supportManagerFunction = new lambda.Function(this, 'SupportManagerFunction', {
      ...commonProps,
      description: 'Handles support requests and forwards to GitHub/Email',
      code: lambda.Code.fromAsset(path.join(backendPath, 'support_manager')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      environment: {
        ...commonProps.environment,
        GITHUB_SUPPORT_REPO: process.env.GITHUB_SUPPORT_REPO || 'marioalvarez/conversacion',
      }
    });

    // Grant SSM access to get GitHub Token
    this.supportManagerFunction.addToRolePolicy(new iam.PolicyStatement({
      actions: ['ssm:GetParameter'],
      resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter/chat-booking/github-token`],
    }));

    // 15b. Public Link Status Lambda
    this.publicLinkStatusFunction = new lambda.Function(this, 'PublicLinkStatusFunction', {
      ...commonProps,
      description: 'Manage public link publication status (isPublished, checklist)',
      code: lambda.Code.fromAsset(path.join(backendPath, 'public_link_status')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      environment: {
        ...commonProps.environment,
        PUBLIC_LINK_BASE_URL: props.envName === 'prod' ? 'https://agendar.holalucia.cl' : `https://agendar.${props.envName}.holalucia.cl`,
      },
    });

    // Grant permissions
    props.tenantsTable.grantReadWriteData(this.publicLinkStatusFunction);
    props.servicesTable.grantReadData(this.publicLinkStatusFunction);
    props.providersTable.grantReadData(this.publicLinkStatusFunction);
    props.availabilityTable.grantReadData(this.publicLinkStatusFunction);
    props.roomsTable.grantReadData(this.publicLinkStatusFunction);

    // Explicitly grant access to indices for Rooms table
    this.publicLinkStatusFunction.addToRolePolicy(new iam.PolicyStatement({
      actions: ['dynamodb:Query', 'dynamodb:GetItem', 'dynamodb:Scan'],
      resources: [
        props.roomsTable.tableArn,
        `${props.roomsTable.tableArn}/index/*`
      ],
    }));
    props.userPool.grant(this.publicLinkStatusFunction, 'cognito-idp:AdminGetUser');

    // 16. Google Integration Lambda
    this.googleIntegrationFunction = new lambda.Function(this, 'GoogleIntegrationFunction', {
      ...commonProps,
      description: 'Google Calendar OAuth Handler',
      code: lambda.Code.fromAsset(path.join(backendPath, 'google_integration')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      environment: {
        ...commonProps.environment,
        GOOGLE_CLIENT_ID: process.env.GOOGLE_CLIENT_ID || '',
        GOOGLE_CLIENT_SECRET: process.env.GOOGLE_CLIENT_SECRET || '',
        // We will need the Redirect URI here too? 
        // Actually the handler constructs it from the request event (Host header) usually for Lambda URLs
        // But for correctness let's pass it if we knew it, but circular dependency.
        // The handler should use the 'Host' header to build the redirect URI.
      }
    });

    // 19. CAF Manager Lambda
    this.cafManagerFunction = new lambda.Function(this, 'CafManagerFunction', {
      ...commonProps,
      description: 'Manager for uploading CAF XMLs and extracting folio limits',
      code: lambda.Code.fromAsset(path.join(backendPath, 'caf_manager')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
    });

    // Grant permissions
    props.dteFoliosTable.grantReadWriteData(this.cafManagerFunction);
    props.userPool.grant(this.cafManagerFunction, 'cognito-idp:AdminGetUser');

    // Add Function URL
    const googleIntegrationUrl = this.googleIntegrationFunction.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
    });

    // Grant permissions
    props.providersTable.grantReadWriteData(this.googleIntegrationFunction); // To store tokens

    // 18. Microsoft Integration Lambda
    this.microsoftIntegrationFunction = new lambda.Function(this, 'MicrosoftIntegrationFunction', {
      ...commonProps,
      description: 'Microsoft Outlook Calendar OAuth Handler',
      code: lambda.Code.fromAsset(path.join(backendPath, 'microsoft_integration')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      environment: {
        ...commonProps.environment,
        MICROSOFT_CLIENT_ID: process.env.MICROSOFT_CLIENT_ID || '',
        MICROSOFT_CLIENT_SECRET: process.env.MICROSOFT_CLIENT_SECRET || '',
      }
    });

    // Add Function URL
    const microsoftIntegrationUrl = this.microsoftIntegrationFunction.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
    });

    // Grant permissions
    props.providersTable.grantReadWriteData(this.microsoftIntegrationFunction); // To store tokens

    // 13. Ingestion Function (Knowledge Base - S3 Trigger)
    // Create Documents Bucket (Moved from VectorDatabaseStack to avoid cyclic dependency)
    this.documentsBucket = new s3.Bucket(this, 'DocumentsBucket', {
      versioned: true,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      cors: [
        {
          allowedMethods: [s3.HttpMethods.PUT],
          allowedOrigins: ['*'], // In prod, restrict to CloudFront domain
          allowedHeaders: ['*'],
        }
      ],
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    this.ingestionFunction = new lambda.Function(this, 'IngestionFunction', {
      ...commonProps,
      description: 'Document ingestion logic (RAG) - Triggered by S3',
      code: lambda.Code.fromAsset(path.join(backendPath, 'knowledge_base')),
      handler: 'ingestion_handler.lambda_handler', // Specific handler
      layers: [sharedLayer],
      timeout: cdk.Duration.seconds(300),
      memorySize: 1024,
      environment: {
        ...commonProps.environment,
        // DB_SECRET_ARN: props.dbSecret?.secretArn || '',
        // DB_ENDPOINT: props.dbEndpoint || '',
      }
    });

    // S3 Trigger
    this.documentsBucket.addEventNotification(
      s3.EventType.OBJECT_CREATED,
      new s3n.LambdaDestination(this.ingestionFunction)
    );
    this.documentsBucket.grantRead(this.ingestionFunction);

    // Grant permissions for Ingestion
    props.tenantsTable.grantReadData(this.ingestionFunction);
    // if (props.dbSecret) {
    //   props.dbSecret.grantRead(this.ingestionFunction);
    // }

    // Grant Bedrock
    this.ingestionFunction.addToRolePolicy(new cdk.aws_iam.PolicyStatement({
      actions: ['bedrock:InvokeModel'],
      resources: ['*'],
    }));

    // Grant RDS Data API - REMOVED
    /*
    if (props.dbEndpoint) {
      this.ingestionFunction.addToRolePolicy(new cdk.aws_iam.PolicyStatement({
        actions: ['rds-data:ExecuteStatement', 'rds-data:BatchExecuteStatement'],
        resources: [props.dbEndpoint],
      }));
    }
    */

    // 13. Presign Function (Get Upload URL)
    this.presignFunction = new lambda.Function(this, 'PresignFunction', {
      ...commonProps,
      description: 'Generate S3 Presigned URLs for uploads',
      code: lambda.Code.fromAsset(path.join(backendPath, 'knowledge_base')),
      handler: 'presign_handler.lambda_handler',
      layers: [sharedLayer],
      environment: {
        ...commonProps.environment,
        DOCUMENTS_BUCKET: this.documentsBucket.bucketName,
        DOCUMENTS_TABLE: props.documentsTable.tableName,
        ASSETS_BUCKET: props.assetsBucketName || '',
        // For debugging purposes in CloudWatch
        ASSETS_BUCKET_NAME: props.assetsBucketName || 'NOT_CONFIGURED',
      }
    });

    this.documentsBucket.grantWrite(this.presignFunction); // Allow putting objects (presigning)

    // Grant write to Assets Bucket if provided
    if (assetsBucket) {
      assetsBucket.grantPut(this.presignFunction);
    }
    // cdk grantWrite actually allows PutObject*
    props.tenantsTable.grantReadData(this.presignFunction); // To check plan/limits
    props.documentsTable.grantReadWriteData(this.presignFunction); // Create PENDING record
    props.documentsTable.grantReadWriteData(this.ingestionFunction); // Update status to INDEXED

    // Grant AdminGetUser to fetch tenantId if missing in claims
    this.presignFunction.addEnvironment('USER_POOL_ID', props.userPool.userPoolId);
    props.userPool.grant(this.presignFunction, 'cognito-idp:AdminGetUser');

    // CloudWatch alarms for critical functions
    this.createAlarms();

    // Outputs
    new cdk.CfnOutput(this, 'AuthResolverFunctionArn', {
      value: this.authResolverFunction.functionArn,
      description: 'Auth Resolver Lambda ARN',
    });

    new cdk.CfnOutput(this, 'CatalogFunctionArn', {
      value: this.catalogFunction.functionArn,
      description: 'Catalog Lambda ARN',
    });

    new cdk.CfnOutput(this, 'AvailabilityFunctionArn', {
      value: this.availabilityFunction.functionArn,
      description: 'Availability Lambda ARN',
    });

    new cdk.CfnOutput(this, 'BookingFunctionArn', {
      value: this.bookingFunction.functionArn,
      description: 'Booking Lambda ARN',
    });

    new cdk.CfnOutput(this, 'ChatAgentFunctionArn', {
      value: this.chatAgentFunction.functionArn,
      description: 'Chat Agent Lambda ARN',
    });

    new cdk.CfnOutput(this, 'WorkflowManagerFunctionArn', {
      value: this.workflowManagerFunction.functionArn,
      description: 'Workflow Manager Lambda ARN',
    });

    new cdk.CfnOutput(this, 'FaqManagerFunctionArn', {
      value: this.faqManagerFunction.functionArn,
      description: 'FAQ Manager Lambda ARN',
    });

    new cdk.CfnOutput(this, 'IngestionFunctionArn', {
      value: this.ingestionFunction.functionArn,
      description: 'Ingestion Lambda ARN',
    });

    new cdk.CfnOutput(this, 'GoogleIntegrationUrl', {
      value: googleIntegrationUrl.url,
      description: 'Google Integration Callback URL',
    });

    new cdk.CfnOutput(this, 'MicrosoftIntegrationUrl', {
      value: microsoftIntegrationUrl.url,
      description: 'Microsoft Integration Callback URL',
    });


    // Import Link resources from SSM
    const linkBucketName = ssm.StringParameter.valueForStringParameter(
      this, `/chatbooking/${props.envName}/link-bucket-name`
    );
    const linkDistributionId = ssm.StringParameter.valueForStringParameter(
      this, `/chatbooking/${props.envName}/link-distribution-id`
    );
    
    // Import Subscriptions Table Name from SSM
    const subscriptionsTableNameSsm = ssm.StringParameter.valueForStringParameter(
      this, `/chatbooking/${props.envName}/subscriptions-table-name`
    );

    const profileBakerFunction = new lambda.Function(this, 'ProfileBakerFunction', {
      ...commonProps,
      description: 'Generates SEO-optimized HTML for tenant profiles (triggered by DynamoDB)',
      code: lambda.Code.fromAsset(path.join(backendPath, 'profile_baker')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      timeout: cdk.Duration.seconds(30),
      environment: {
        ...commonProps.environment,
        LINK_BUCKET: linkBucketName,
        DISTRIBUTION_ID: linkDistributionId,
        PUBLIC_LINK_BASE_URL: props.envName === 'prod' ? 'https://agendar.holalucia.cl' : `https://agendar.${props.envName}.holalucia.cl`,
      }
    });

    // Grant permissions
    // 1. DynamoDB Stream Triggers
    profileBakerFunction.addEventSource(new lambdaEventSources.DynamoEventSource(props.tenantsTable, {
      startingPosition: lambda.StartingPosition.LATEST,
      retryAttempts: 2,
      filters: [
        lambda.FilterCriteria.filter({
          eventName: lambda.FilterRule.or('INSERT', 'MODIFY'),
        }),
      ],
    }));

    profileBakerFunction.addEventSource(new lambdaEventSources.DynamoEventSource(props.providersTable, {
      startingPosition: lambda.StartingPosition.LATEST,
      retryAttempts: 2,
      filters: [
        lambda.FilterCriteria.filter({
          eventName: lambda.FilterRule.or('INSERT', 'MODIFY'),
        }),
      ],
    }));

    // Grant read access to the stream source tables
    props.tenantsTable.grantReadData(profileBakerFunction);
    props.providersTable.grantReadData(profileBakerFunction);

    // 2. S3 Write Access to Link Bucket
    const linkBucket = s3.Bucket.fromBucketName(this, 'ImportedLinkBucket', linkBucketName);
    linkBucket.grantReadWrite(profileBakerFunction);

    // 3. CloudFront Invalidation Permission
    profileBakerFunction.addToRolePolicy(new cdk.aws_iam.PolicyStatement({
      actions: ['cloudfront:CreateInvalidation'],
      resources: [`arn:aws:cloudfront::${this.account}:distribution/${linkDistributionId}`],
    }));

    // Start Full Bake Permissions
    props.servicesTable.grantReadData(profileBakerFunction);
    props.providersTable.grantReadData(profileBakerFunction);
    // End Full Bake Permissions

    // 19. Check Payment Status Lambda (Reconciliation)
    this.checkPaymentStatusFunction = new lambda.Function(this, 'CheckPaymentStatusFunction', {
      ...commonProps,
      description: 'Check payment status against Mercado Pago for reconciliation',
      code: lambda.Code.fromAsset(path.join(backendPath, 'subscriptions/handlers')),
      handler: 'check_payment_status.lambda_handler',
      layers: [sharedLayer],
      environment: {
        ...commonProps.environment,
        SUBSCRIPTIONS_TABLE: subscriptionsTableNameSsm,
        MP_ACCESS_TOKEN: secretsmanager.Secret.fromSecretNameV2(this, 'MPSecretCheck', 'ChatBooking/MercadoPago')
          .secretValueFromJson('ACCESS_TOKEN').unsafeUnwrap(),
      }
    });

    // Grant permissions — table reconstructed from name to avoid cross-stack CFN export coupling
    const subscriptionsTable = dynamodb.Table.fromTableName(this, 'SubscriptionsTable', subscriptionsTableNameSsm);
    subscriptionsTable.grantReadWriteData(this.checkPaymentStatusFunction);
    props.tenantsTable.grantReadWriteData(this.checkPaymentStatusFunction);

    // 20. Clients Lambda (Client File)
    this.clientsFunction = new lambda.Function(this, 'ClientsFunction', {
      ...commonProps,
      description: 'Client File Management (CRUD)',
      code: lambda.Code.fromAsset(path.join(backendPath, 'clients')), // Path to 'clients' dir
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      environment: {
        ...commonProps.environment,
        CLIENTS_TABLE: props.clientsTable.tableName,
        // Encryption Key ID will be needed here later
      }
    });

    // Grant permissions
    props.clientsTable.grantReadWriteData(this.clientsFunction);
    new cdk.CfnOutput(this, 'ClientsFunctionArn', {
      value: this.clientsFunction.functionArn,
      description: 'Clients Lambda ARN',
    });
    props.userPool.grant(this.clientsFunction, 'cognito-idp:AdminGetUser');

    // 21. SII Scraper Function (Puppeteer Auto-Provisioning)
    this.siiScraperFunction = new lambda.Function(this, 'SiiScraperFunction', {
      runtime: lambda.Runtime.NODEJS_22_X,
      code: lambda.Code.fromAsset(path.join(backendPath, 'sii_scraper')),
      handler: 'index.handler',
      timeout: cdk.Duration.minutes(5), // Scraping can be slow
      memorySize: 2048, // Headless chrome needs memory
      environment: {
        DTE_FOLIOS_TABLE: props.dteFoliosTable.tableName,
        TENANTS_TABLE: props.tenantsTable.tableName,
      },
      logRetention: logs.RetentionDays.ONE_WEEK,
    });
    props.dteFoliosTable.grantReadWriteData(this.siiScraperFunction);

    // Allow reading from secrets manager for the SII credentials
    this.siiScraperFunction.addToRolePolicy(new iam.PolicyStatement({
      actions: ['secretsmanager:GetSecretValue'],
      resources: [`arn:aws:secretsmanager:${cdk.Aws.REGION}:${cdk.Aws.ACCOUNT_ID}:secret:prod/sii/credentials/*`]
    }));

    // 22. Client Synchronization Lambda (Stream Trigger)
    this.clientSyncFunction = new lambda.Function(this, 'ClientSyncFunction', {
      ...commonProps,
      description: 'Synchronizes Booking data to Client File automatically',
      code: lambda.Code.fromAsset(path.join(backendPath, 'clients')),
      handler: 'sync_handler.lambda_handler',
      layers: [sharedLayer],
      environment: {
        ...commonProps.environment,
        CLIENTS_TABLE: props.clientsTable.tableName,
        CLIENT_AUDIT_LOGS_TABLE: props.clientAuditLogsTable.tableName,
        BOOKINGS_TABLE: props.bookingsTable.tableName,
      }
    });

    // Permissions for Sync
    props.clientsTable.grantReadWriteData(this.clientSyncFunction);
    props.clientAuditLogsTable.grantReadWriteData(this.clientSyncFunction);
    props.bookingsTable.grantReadData(this.clientSyncFunction);

    // Also update main Clients Lambda to write audit logs
    this.clientsFunction.addEnvironment('CLIENT_AUDIT_LOGS_TABLE', props.clientAuditLogsTable.tableName);
    props.clientAuditLogsTable.grantReadWriteData(this.clientsFunction);

    // Add DynamoDB Stream Trigger on Bookings Table
    this.clientSyncFunction.addEventSource(new lambdaEventSources.DynamoEventSource(props.bookingsTable, {
      startingPosition: lambda.StartingPosition.LATEST,
      retryAttempts: 2,
      filters: [
        lambda.FilterCriteria.filter({
          eventName: lambda.FilterRule.isEqual('INSERT'), // Only on new bookings
        }),
      ],
    }));
    // 23. WhatsApp Sender Lambda (SQS Triggered)
    this.whatsappSenderFunction = new lambda.Function(this, 'WhatsappSenderFunction', {
      ...commonProps,
      description: 'Processes messages from SQS, checks quota, and sends via Twilio/ISV',
      code: lambda.Code.fromAsset(path.join(backendPath, 'backend', 'whatsapp_sender')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      timeout: cdk.Duration.seconds(30),
      environment: {
        ...commonProps.environment,
        WHATSAPP_MESSAGES_TABLE: props.whatsappMessagesTable.tableName,
        TWILIO_ACCOUNT_SID: process.env.TWILIO_ACCOUNT_SID || '',
        TWILIO_AUTH_TOKEN: process.env.TWILIO_AUTH_TOKEN || '',
      }
    });

    // Add SQS Event Source
    this.whatsappSenderFunction.addEventSource(new lambdaEventSources.SqsEventSource(props.whatsappSenderQueue, {
      batchSize: 10,
      maxBatchingWindow: cdk.Duration.seconds(5),
    }));

    // Grant permissions to Sender
    props.tenantsTable.grantReadWriteData(this.whatsappSenderFunction); // To read plan and update used quota
    props.whatsappMessagesTable.grantReadWriteData(this.whatsappSenderFunction);
    props.tenantUsageTable.grantWriteData(this.whatsappSenderFunction); // For quota exhaustion metrics
    props.waitlistPendingTable.grantReadWriteData(this.whatsappSenderFunction);

    // Explicitly grant KMS decrypt if SQS is encrypted with AWS managed key
    props.whatsappSenderQueue.grantConsumeMessages(this.whatsappSenderFunction);

    // 24. WhatsApp Webhook Lambda
    this.whatsappWebhookFunction = new lambda.Function(this, 'WhatsappWebhookFunction', {
      ...commonProps,
      description: 'Receives delivery status and inbound messages from Twilio/ISV',
      code: lambda.Code.fromAsset(path.join(backendPath, 'backend', 'whatsapp_webhook')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      environment: {
        ...commonProps.environment,
        WHATSAPP_MESSAGES_TABLE: props.whatsappMessagesTable.tableName,
        TWILIO_AUTH_TOKEN: process.env.TWILIO_AUTH_TOKEN || '',
        WHATSAPP_SENDER_QUEUE_URL: props.whatsappSenderQueue.queueUrl,
        CLIENTS_TABLE: props.clientsTable.tableName,
      }
    });

    // Grant permissions to Webhook
    props.whatsappMessagesTable.grantReadWriteData(this.whatsappWebhookFunction);
    props.waitlistPendingTable.grantReadWriteData(this.whatsappWebhookFunction);
    props.waitingListTable.grantReadWriteData(this.whatsappWebhookFunction);
    props.bookingsTable.grantReadWriteData(this.whatsappWebhookFunction);
    props.tenantsTable.grantReadData(this.whatsappWebhookFunction);
    props.providersTable.grantReadData(this.whatsappWebhookFunction);
    props.availabilityTable.grantReadData(this.whatsappWebhookFunction);
    props.clientsTable.grantReadData(this.whatsappWebhookFunction);
    props.whatsappSenderQueue.grantSendMessages(this.whatsappWebhookFunction);

    // Add Function URL for webhook
    const whatsappWebhookUrl = this.whatsappWebhookFunction.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
    });

    new cdk.CfnOutput(this, 'WhatsappWebhookUrl', {
      value: whatsappWebhookUrl.url,
      description: 'Public URL to configure in Twilio/ISV as the WhatsApp webhook',
    });

    // 25. Twilio Connect Lambda (OAuth Embedded Signup callback)
    const twilioMasterSecret = secretsmanager.Secret.fromSecretNameV2(
      this, 'TwilioMasterSecret', 'prod/twilio/master'
    );

    this.twilioConnectFunction = new lambda.Function(this, 'TwilioConnectFunction', {
      ...commonProps,
      description: 'Handles Twilio Embedded Signup OAuth callback and stores per-tenant WABA credentials',
      code: lambda.Code.fromAsset(path.join(backendPath, 'backend', 'twilio_connect')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      timeout: cdk.Duration.seconds(30),
      environment: {
        ...commonProps.environment,
        TWILIO_MASTER_SECRET_NAME: 'prod/twilio/master',
        DASHBOARD_BASE_URL: props.envName === 'prod' ? 'https://admin.holalucia.cl' : `https://control.${props.envName}.holalucia.cl`,
        TWILIO_CONNECTED_APP_SID: process.env.TWILIO_CONNECTED_APP_SID || '',
        TWILIO_CONNECTED_APP_SECRET: process.env.TWILIO_CONNECTED_APP_SECRET || '',
      }
    });

    // Secrets Manager read access for master Twilio credentials
    twilioMasterSecret.grantRead(this.twilioConnectFunction);

    // DynamoDB write access to update tenant settings
    props.tenantsTable.grantReadWriteData(this.twilioConnectFunction);

    // Public HTTP Function URL for OAuth redirect
    const twilioConnectUrl = this.twilioConnectFunction.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
    });

    new cdk.CfnOutput(this, 'TwilioConnectCallbackUrl', {
      value: twilioConnectUrl.url,
      description: 'Redirect URI to register in Twilio Connected App (OAuth callback)',
    });

    // 26. WhatsApp Scheduler Lambda (reads tenant rules → EventBridge Scheduler)
    this.whatsappSchedulerFunction = new lambda.Function(this, 'WhatsappSchedulerFunction', {
      ...commonProps,
      description: 'Reads tenant notification rules and schedules timed WhatsApp reminders via EventBridge Scheduler',
      code: lambda.Code.fromAsset(path.join(backendPath, 'backend')),
      handler: 'whatsapp_scheduler.handler.lambda_handler',
      layers: [sharedLayer],
      timeout: cdk.Duration.seconds(60),
      environment: {
        ...commonProps.environment,
        WHATSAPP_SNS_TOPIC_ARN: props.whatsappNotificationTopic.topicArn,
        SCHEDULER_GROUP_NAME: props.whatsappSchedulerGroupName || 'ChatBooking-WhatsappSchedules',
        SCHEDULER_ROLE_ARN: props.whatsappSchedulerRoleArn || '',
      }
    });

    // DynamoDB read for tenant rules
    props.tenantsTable.grantReadData(this.whatsappSchedulerFunction);

    // SNS publish for immediate (on_booking) notifications
    props.whatsappNotificationTopic.grantPublish(this.whatsappSchedulerFunction);

    // EventBridge Scheduler permissions to create/delete schedules
    this.whatsappSchedulerFunction.addToRolePolicy(new iam.PolicyStatement({
      actions: [
        'scheduler:CreateSchedule',
        'scheduler:DeleteSchedule',
        'scheduler:GetSchedule',
      ],
      resources: [`arn:aws:scheduler:${this.region}:${this.account}:schedule/ChatBooking-WhatsappSchedules/*`],
    }));
    // Pass role so EventBridge Scheduler can publish to SNS
    this.whatsappSchedulerFunction.addToRolePolicy(new iam.PolicyStatement({
      actions: ['iam:PassRole'],
      resources: [props.whatsappSchedulerRoleArn || '*'],
    }));

    // Subscribe this Lambda directly to the SNS topic (filtered to BOOKING_CONFIRMED)
    props.whatsappNotificationTopic.addSubscription(
      new (require('aws-cdk-lib/aws-sns-subscriptions').LambdaSubscription)(this.whatsappSchedulerFunction, {
        filterPolicy: {
          event_type: cdk.aws_sns.SubscriptionFilter.stringFilter({
            allowlist: ['BOOKING_CONFIRMED'],
          }),
        },
      })
    );

    // 27. Notification Scheduler Lambda (email + SMS hours_before reminders)
    // IAM role for EventBridge Scheduler to invoke this Lambda
    const notifSchedulerRole = new iam.Role(this, 'NotifSchedulerInvokeRole', {
      roleName: 'ChatBooking-NotifSchedulerInvokeRole',
      assumedBy: new iam.ServicePrincipal('scheduler.amazonaws.com'),
      description: 'Allows EventBridge Scheduler to invoke notification_scheduler Lambda',
    });
    const notifSchedulerGroup = new (require('aws-cdk-lib/aws-scheduler').CfnScheduleGroup)(
      this, 'NotifSchedulerGroup', { name: 'ChatBooking-NotificationSchedules' }
    );

    this.notificationSchedulerFunction = new lambda.Function(this, 'NotificationSchedulerFunction', {
      ...commonProps,
      description: 'Schedules and fires email/SMS reminders for booking notifications',
      code: lambda.Code.fromAsset(path.join(backendPath, 'backend')),
      handler: 'notification_scheduler.handler.lambda_handler',
      layers: [sharedLayer],
      timeout: cdk.Duration.seconds(60),
      environment: {
        ...commonProps.environment,
        // ARN is read at runtime via context.invoked_function_arn (avoids circular dep)
        NOTIFICATION_SCHEDULER_ROLE_ARN: notifSchedulerRole.roleArn,
        NOTIFICATION_SCHEDULER_GROUP: 'ChatBooking-NotificationSchedules',
        SES_SENDER_EMAIL: props.envName === 'prod' ? 'no-reply@mail.holalucia.cl' : 'holalucia.ai@gmail.com',
      },
    });

    // Allow EventBridge Scheduler to invoke this Lambda
    notifSchedulerRole.addToPolicy(new iam.PolicyStatement({
      actions: ['lambda:InvokeFunction'],
      resources: [this.notificationSchedulerFunction.functionArn],
    }));

    // DynamoDB read for tenant settings
    props.tenantsTable.grantReadData(this.notificationSchedulerFunction);

    // SES send permission
    this.notificationSchedulerFunction.addToRolePolicy(new iam.PolicyStatement({
      actions: ['ses:SendEmail', 'ses:SendRawEmail'],
      resources: ['*'],
    }));

    // SNS publish for SMS (direct publish, not topic)
    this.notificationSchedulerFunction.addToRolePolicy(new iam.PolicyStatement({
      actions: ['sns:Publish'],
      resources: ['*'],
    }));

    // EventBridge Scheduler permissions (create/delete reminder schedules)
    this.notificationSchedulerFunction.addToRolePolicy(new iam.PolicyStatement({
      actions: ['scheduler:CreateSchedule', 'scheduler:DeleteSchedule', 'scheduler:GetSchedule'],
      resources: [`arn:aws:scheduler:${this.region}:${this.account}:schedule/ChatBooking-NotificationSchedules/*`],
    }));
    this.notificationSchedulerFunction.addToRolePolicy(new iam.PolicyStatement({
      actions: ['iam:PassRole'],
      resources: [notifSchedulerRole.roleArn],
    }));

    // Subscribe to BOOKING_CONFIRMED events on the WhatsApp SNS topic
    props.whatsappNotificationTopic.addSubscription(
      new (require('aws-cdk-lib/aws-sns-subscriptions').LambdaSubscription)(this.notificationSchedulerFunction, {
        filterPolicy: {
          event_type: cdk.aws_sns.SubscriptionFilter.stringFilter({
            allowlist: ['BOOKING_CONFIRMED'],
          }),
        },
      })
    );

    // 28. Waitlist API Lambda
    this.waitlistApiFunction = new lambda.Function(this, 'WaitlistApiFunction', {
      ...commonProps,
      description: 'GraphQL API resolvers for the Waitlist feature',
      code: lambda.Code.fromAsset(path.join(backendPath, 'waitlist_api')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      timeout: cdk.Duration.seconds(30),
    });

    // Grant permissions
    props.waitingListTable.grantReadWriteData(this.waitlistApiFunction);
    props.tenantsTable.grantReadData(this.waitlistApiFunction);
    props.providersTable.grantReadData(this.waitlistApiFunction);
    props.availabilityTable.grantReadData(this.waitlistApiFunction);
    props.servicesTable.grantReadData(this.waitlistApiFunction);
    props.bookingsTable.grantReadData(this.waitlistApiFunction);

    // Waitlist Trigger Lambda (DynamoDB Stream from Bookings)
    this.waitlistTriggerFunction = new lambda.Function(this, 'WaitlistTriggerFunction', {
      ...commonProps,
      description: 'Processes booking cancellations and notifies waitlist candidates',
      code: lambda.Code.fromAsset(path.join(backendPath, 'waitlist_trigger')),
      handler: 'handler.handler',
      layers: [sharedLayer],
      timeout: cdk.Duration.seconds(60),
      memorySize: 256,
      environment: {
        ...commonProps.environment,
        WHATSAPP_SENDER_QUEUE_URL: props.whatsappSenderQueue.queueUrl,
      },
    });

    // Grant permissions
    props.waitingListTable.grantReadWriteData(this.waitlistTriggerFunction);
    props.bookingsTable.grantReadWriteData(this.waitlistTriggerFunction);
    props.tenantsTable.grantReadData(this.waitlistTriggerFunction);
    props.providersTable.grantReadData(this.waitlistTriggerFunction);
    props.availabilityTable.grantReadData(this.waitlistTriggerFunction);
    props.whatsappSenderQueue.grantSendMessages(this.waitlistTriggerFunction);

    // DynamoDB Stream event source from Bookings table
    this.waitlistTriggerFunction.addEventSource(
      new lambdaEventSources.DynamoEventSource(props.bookingsTable, {
        startingPosition: lambda.StartingPosition.TRIM_HORIZON,
        batchSize: 10,
        maxBatchingWindow: cdk.Duration.seconds(5),
        retryAttempts: 3,
        filters: [
          lambda.FilterCriteria.filter({
            eventName: lambda.FilterRule.isEqual('MODIFY'),
            'dynamodb.NewImage.status.S': lambda.FilterRule.isEqual('CANCELLED'),
            'dynamodb.OldImage.status.S': lambda.FilterRule.notEquals('CANCELLED'),
          })
        ]
      })
    );
  }

  private createAlarms(): void {
    // Create CloudWatch alarms for critical functions
    const functions = [
      { name: 'AuthResolver', fn: this.authResolverFunction },
      { name: 'Booking', fn: this.bookingFunction },
      { name: 'ChatAgent', fn: this.chatAgentFunction },
      { name: 'RegisterTenant', fn: this.registerTenantFunction },
    ];

    functions.forEach(({ name, fn }) => {
      // Error rate alarm
      const errorMetric = fn.metricErrors({
        period: cdk.Duration.minutes(5),
        statistic: 'Sum',
      });

      new cdk.aws_cloudwatch.Alarm(this, `${name}ErrorAlarm`, {
        metric: errorMetric,
        threshold: 10,
        evaluationPeriods: 1,
        alarmDescription: `${name} Lambda errors exceed threshold`,
        treatMissingData: cdk.aws_cloudwatch.TreatMissingData.NOT_BREACHING,
      });

      // Throttle alarm
      const throttleMetric = fn.metricThrottles({
        period: cdk.Duration.minutes(5),
        statistic: 'Sum',
      });

      new cdk.aws_cloudwatch.Alarm(this, `${name}ThrottleAlarm`, {
        metric: throttleMetric,
        threshold: 5,
        evaluationPeriods: 1,
        alarmDescription: `${name} Lambda throttles exceed threshold`,
        treatMissingData: cdk.aws_cloudwatch.TreatMissingData.NOT_BREACHING,
      });

      // Duration alarm (P99)
      const durationMetric = fn.metricDuration({
        period: cdk.Duration.minutes(5),
        statistic: 'p99',
      });

      new cdk.aws_cloudwatch.Alarm(this, `${name}DurationAlarm`, {
        metric: durationMetric,
        threshold: fn.timeout!.toMilliseconds() * 0.8, // 80% of timeout
        evaluationPeriods: 2,
        alarmDescription: `${name} Lambda duration high (P99)`,
        treatMissingData: cdk.aws_cloudwatch.TreatMissingData.NOT_BREACHING,
      });
    });
  }
}
