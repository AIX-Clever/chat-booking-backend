import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as logs from 'aws-cdk-lib/aws-logs';
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
}

export class LambdaStack extends cdk.Stack {
  public readonly authResolverFunction: lambda.Function;
  public readonly catalogFunction: lambda.Function;
  public readonly availabilityFunction: lambda.Function;
  public readonly bookingFunction: lambda.Function;
  public readonly chatAgentFunction: lambda.Function;

  constructor(scope: Construct, id: string, props: LambdaStackProps) {
    super(scope, id, props);

    // Get backend code path (relative to infra/lib)
    const backendPath = path.join(__dirname, '../../');

    // Common Lambda configuration
    const commonProps = {
      runtime: lambda.Runtime.PYTHON_3_9,
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
        LOG_LEVEL: 'INFO',
      },
    };

    // Lambda Layer for shared code
    // Note: CI/CD creates shared_layer/python/shared/ structure for proper Lambda layer import
    const sharedLayer = new lambda.LayerVersion(this, 'SharedLayer', {
      code: lambda.Code.fromAsset(path.join(backendPath, 'shared_layer')),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_9],
      description: 'Shared domain entities, repositories, and utilities',
    });

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
    });

    // Grant permissions - chat agent needs access to everything
    props.conversationsTable.grantReadWriteData(this.chatAgentFunction);
    props.servicesTable.grantReadData(this.chatAgentFunction);
    props.providersTable.grantReadData(this.chatAgentFunction);
    props.availabilityTable.grantReadData(this.chatAgentFunction);
    props.bookingsTable.grantReadWriteData(this.chatAgentFunction);

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
  }

  private createAlarms(): void {
    // Create CloudWatch alarms for critical functions
    const functions = [
      { name: 'AuthResolver', fn: this.authResolverFunction },
      { name: 'Booking', fn: this.bookingFunction },
      { name: 'ChatAgent', fn: this.chatAgentFunction },
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
