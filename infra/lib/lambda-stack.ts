import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
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
  userPool: cdk.aws_cognito.IUserPool;
  vpc?: cdk.aws_ec2.IVpc;
  dbSecurityGroup?: cdk.aws_ec2.ISecurityGroup;
  dbSecret?: cdk.aws_secretsmanager.ISecret;
  dbEndpoint?: string; // Cluster ARN for Data API
}

export class LambdaStack extends cdk.Stack {
  public readonly authResolverFunction: lambda.Function;
  public readonly catalogFunction: lambda.Function;
  public readonly availabilityFunction: lambda.Function;
  public readonly bookingFunction: lambda.Function;
  public readonly chatAgentFunction: lambda.Function;
  public readonly registerTenantFunction: lambda.Function;
  public readonly updateTenantFunction: lambda.Function;
  public readonly getTenantFunction: lambda.Function;
  public readonly metricsFunction: lambda.Function;
  public readonly workflowManagerFunction: lambda.Function;
  public readonly faqManagerFunction: lambda.Function;

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
      },
    };

    // Lambda Layer for shared code
    // Imported from SSM Parameter (updated by chat-booking-layers stack)
    const layerArn = ssm.StringParameter.valueForStringParameter(
      this, '/chatbooking/layers/python-layer-arn'
    );
    const sharedLayer = lambda.LayerVersion.fromLayerVersionArn(this, 'SharedLayer', layerArn);

    // 1. Auth Resolver Lambda
    this.authResolverFunction = new lambda.Function(this, 'AuthResolverFunction', {
      ...commonProps,
      functionName: 'ChatBooking-AuthResolver',
      description: 'AppSync authorizer - validates API keys and returns tenant context',
      code: lambda.Code.fromAsset(path.join(backendPath, 'auth_resolver')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      timeout: cdk.Duration.seconds(10), // Fast for auth
      memorySize: 256, // Less memory for simple validation
    });

    // Grant permissions
    props.tenantsTable.grantReadData(this.authResolverFunction);
    props.apiKeysTable.grantReadWriteData(this.authResolverFunction); // WriteData for lastUsedAt update

    // 2. Catalog Lambda
    this.catalogFunction = new lambda.Function(this, 'CatalogFunction', {
      ...commonProps,
      functionName: 'ChatBooking-Catalog',
      description: 'Service and provider catalog management',
      code: lambda.Code.fromAsset(path.join(backendPath, 'catalog')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
    });

    // Grant permissions
    props.servicesTable.grantReadWriteData(this.catalogFunction);
    props.providersTable.grantReadWriteData(this.catalogFunction);
    props.categoriesTable.grantReadWriteData(this.catalogFunction);

    // 3. Availability Lambda
    this.availabilityFunction = new lambda.Function(this, 'AvailabilityFunction', {
      ...commonProps,
      functionName: 'ChatBooking-Availability',
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
      functionName: 'ChatBooking-Booking',
      description: 'Booking creation, confirmation, and cancellation',
      code: lambda.Code.fromAsset(path.join(backendPath, 'booking')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      timeout: cdk.Duration.seconds(60), // More time for booking validation
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
      functionName: 'ChatBooking-ChatAgent',
      description: 'Conversational FSM agent for booking flow',
      code: lambda.Code.fromAsset(path.join(backendPath, 'chat_agent')),
      handler: 'handler.lambda_handler',
      layers: [sharedLayer],
      timeout: cdk.Duration.seconds(60), // More time for conversation logic
      memorySize: 1024, // More memory for FSM processing
      vpc: props.vpc,
      securityGroups: props.dbSecurityGroup ? [props.dbSecurityGroup] : undefined,
      environment: {
        ...commonProps.environment,
        DB_SECRET_ARN: props.dbSecret?.secretArn || '',
        DB_ENDPOINT: props.dbEndpoint || '',
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
      functionName: 'ChatBooking-RegisterTenant',
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
      functionName: 'ChatBooking-UpdateTenant',
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
      functionName: 'ChatBooking-GetTenant',
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
      functionName: 'ChatBooking-Metrics',
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
      functionName: 'ChatBooking-WorkflowManager',
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
      functionName: 'ChatBooking-FaqManager',
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
        alarmName: `ChatBooking-${name}-Errors`,
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
        alarmName: `ChatBooking-${name}-Throttles`,
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
        alarmName: `ChatBooking-${name}-Duration`,
        treatMissingData: cdk.aws_cloudwatch.TreatMissingData.NOT_BREACHING,
      });
    });
  }
}
