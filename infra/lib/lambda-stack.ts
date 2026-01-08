import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3n from 'aws-cdk-lib/aws-s3-notifications';
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
  userRolesTable: dynamodb.ITable;
  userPool: cdk.aws_cognito.IUserPool;
  vpc?: cdk.aws_ec2.IVpc;
  dbSecurityGroup?: cdk.aws_ec2.ISecurityGroup;
  dbSecret?: cdk.aws_secretsmanager.ISecret;
  dbEndpoint?: string; // Cluster ARN for Data API
  envName: string;
}

export class LambdaStack extends cdk.Stack {
  public readonly authResolverFunction: lambda.Function;
  public readonly catalogFunction: lambda.Function;
  public readonly availabilityFunction: lambda.Function;
  public readonly bookingFunction: lambda.Function;
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

  constructor(scope: Construct, id: string, props: LambdaStackProps) {
    super(scope, id, props);

    // Get backend code path (relative to infra/lib)
    const backendPath = path.join(__dirname, '../../');

    // Common Lambda configuration
    const commonProps = {
      runtime: lambda.Runtime.PYTHON_3_11,
      timeout: cdk.Duration.seconds(30),
      memorySize: 512,
      logRetention: logs.RetentionDays.ONE_WEEK,
      environment: {
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
        LOG_LEVEL: 'INFO',
        // Aliases for legacy/shared code compatibility
        DYNAMODB_WORKFLOWS_TABLE: props.workflowsTable.tableName,
        DYNAMODB_FAQS_TABLE: props.faqsTable.tableName,
        ROOMS_TABLE: props.roomsTable.tableName,
      },
    };

    // Lambda Layer for shared code
    // Imported from SSM Parameter (updated by chat-booking-layers stack)
    const layerArn = ssm.StringParameter.valueForStringParameter(
      this, '/chatbooking/layers/python-layer-arn'
    );
    const sharedLayer = lambda.LayerVersion.fromLayerVersionArn(this, 'SharedLayer', layerArn);
    // Force backend redeploy to pick up latest layer version

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
        ALLOWED_IPS: process.env.ALLOWED_IPS || '181.166.197.80,191.113.67.147', // Use env var if available
      },
    });

    // Grant permissions
    props.tenantsTable.grantReadData(this.authResolverFunction);
    props.apiKeysTable.grantReadWriteData(this.authResolverFunction); // WriteData for lastUsedAt update

    // 2. Catalog Lambda
    this.catalogFunction = new lambda.Function(this, 'CatalogFunction', {
      ...commonProps,
      description: 'Service and provider catalog management',
      code: lambda.Code.fromAsset(path.join(backendPath, 'catalog')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
    });

    // Grant permissions
    props.servicesTable.grantReadWriteData(this.catalogFunction);
    props.providersTable.grantReadWriteData(this.catalogFunction);
    props.categoriesTable.grantReadWriteData(this.catalogFunction);
    props.roomsTable.grantReadWriteData(this.catalogFunction);

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
      },
    });

    // Grant permissions
    props.availabilityTable.grantReadWriteData(this.availabilityFunction);
    props.bookingsTable.grantReadData(this.availabilityFunction); // Read for conflict detection
    props.servicesTable.grantReadData(this.availabilityFunction);
    props.providersTable.grantReadData(this.availabilityFunction);

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
        SES_SENDER_EMAIL: 'noreply@example.com', // Override with actual verified email
        STRIPE_SECRET_KEY: process.env.STRIPE_SECRET_KEY || '', // Passed from GitHub Secrets/Env
      }
    });

    // Grant SES permissions
    this.bookingFunction.addToRolePolicy(new cdk.aws_iam.PolicyStatement({
      actions: ['ses:SendEmail', 'ses:SendRawEmail'],
      resources: ['*'], // In production, restrict to specific identities
    }));

    // 5. Payment Webhook Lambda
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
      }
    });

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
    props.tenantUsageTable.grantWriteData(this.bookingFunction); // For metrics tracking

    // 5. Chat Agent Lambda
    this.chatAgentFunction = new lambda.Function(this, 'ChatAgentFunction', {
      ...commonProps,
      description: 'Conversational FSM agent for booking flow',
      code: lambda.Code.fromAsset(path.join(backendPath, 'chat_agent')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      timeout: cdk.Duration.seconds(120), // More time for conversation logic / RAG
      memorySize: 1024, // More memory for FSM processing
      vpc: props.vpc,
      securityGroups: props.dbSecurityGroup ? [props.dbSecurityGroup] : undefined,
      environment: {
        ...commonProps.environment,
        DB_SECRET_ARN: props.dbSecret?.secretArn || '',
        DB_ENDPOINT: props.dbEndpoint || '',
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

    // Grant Bedrock Access for AI Plans
    this.chatAgentFunction.addToRolePolicy(new cdk.aws_iam.PolicyStatement({
      actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
      resources: ['*'], // Scope this down in production to specific models
    }));

    // Grant RDS Data API Access
    if (props.dbSecret && props.dbEndpoint) {
      props.dbSecret.grantRead(this.chatAgentFunction);
      this.chatAgentFunction.addToRolePolicy(new cdk.aws_iam.PolicyStatement({
        actions: ['rds-data:ExecuteStatement', 'rds-data:BatchExecuteStatement'],
        resources: [props.dbEndpoint], // DB Cluster ARN
      }));
    }

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
      },
      timeout: cdk.Duration.seconds(15),
    });

    // Grant permissions
    props.tenantsTable.grantReadWriteData(this.registerTenantFunction);
    props.apiKeysTable.grantReadWriteData(this.registerTenantFunction);
    props.workflowsTable.grantReadWriteData(this.registerTenantFunction);
    props.userPool.grant(this.registerTenantFunction, 'cognito-idp:AdminCreateUser', 'cognito-idp:AdminSetUserPassword');

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
      },
    });

    // Grant Cognito permissions for user management
    props.userPool.grant(this.userManagementFunction,
      'cognito-idp:AdminCreateUser',
      'cognito-idp:AdminGetUser',
      'cognito-idp:ListUsers',
      'cognito-idp:AdminUpdateUserAttributes',
      'cognito-idp:AdminDisableUser'
    );

    // Grant read access to tenants table for plan validation
    props.tenantsTable.grantReadData(this.userManagementFunction);

    // Grant read/write access to user roles table
    props.userRolesTable.grantReadWriteData(this.userManagementFunction);

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
        DB_SECRET_ARN: props.dbSecret?.secretArn || '',
        DB_ENDPOINT: props.dbEndpoint || '',
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
    if (props.dbSecret) {
      props.dbSecret.grantRead(this.ingestionFunction);
    }

    // Grant Bedrock
    this.ingestionFunction.addToRolePolicy(new cdk.aws_iam.PolicyStatement({
      actions: ['bedrock:InvokeModel'],
      resources: ['*'],
    }));

    // Grant RDS Data API
    if (props.dbEndpoint) {
      this.ingestionFunction.addToRolePolicy(new cdk.aws_iam.PolicyStatement({
        actions: ['rds-data:ExecuteStatement', 'rds-data:BatchExecuteStatement'],
        resources: [props.dbEndpoint],
      }));
    }

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
      }
    });

    this.documentsBucket.grantWrite(this.presignFunction); // Allow putting objects (presigning)
    // cdk grantWrite actually allows PutObject*
    props.tenantsTable.grantReadData(this.presignFunction); // To check plan/limits
    props.documentsTable.grantReadWriteData(this.presignFunction); // Create PENDING record
    props.documentsTable.grantReadWriteData(this.ingestionFunction); // Update status to INDEXED

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
