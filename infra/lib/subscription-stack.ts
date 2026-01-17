import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';
import * as path from 'path';

interface SubscriptionStackProps extends cdk.StackProps {
    tenantsTable: dynamodb.ITable;
    envName: string;
}

export class SubscriptionStack extends cdk.Stack {
    public readonly subscriptionsTable: dynamodb.Table;
    public readonly webhooksQueue: sqs.Queue;
    public readonly webhooksDLQ: sqs.Queue;

    public readonly subscribeFunction: lambda.Function;
    public readonly downgradeFunction: lambda.Function;
    public readonly webhookIngestorFunction: lambda.Function;
    public readonly webhookProcessorFunction: lambda.Function;
    public readonly subscriptionWorkerFunction: lambda.Function;
    public readonly listInvoicesFunction: lambda.Function;

    constructor(scope: Construct, id: string, props: SubscriptionStackProps) {
        super(scope, id, props);

        const backendPath = path.join(process.cwd(), '../');

        // 1. DynamoDB: Subscriptions Table
        this.subscriptionsTable = new dynamodb.Table(this, 'SubscriptionsTable', {
            tableName: 'ChatBooking-Subscriptions',
            partitionKey: {
                name: 'tenantId',
                type: dynamodb.AttributeType.STRING,
            },
            sortKey: {
                name: 'subscriptionId', // 'CURRENT' or specific ID
                type: dynamodb.AttributeType.STRING,
            },
            billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
            pointInTimeRecovery: true,
            removalPolicy: cdk.RemovalPolicy.RETAIN,
        });

        // 2. SQS: Webhooks Queue & DLQ
        this.webhooksDLQ = new sqs.Queue(this, 'WebhooksDLQ', {
            queueName: `ChatBooking-WebhooksDLQ-${props.envName}`,
            retentionPeriod: cdk.Duration.days(14),
        });

        this.webhooksQueue = new sqs.Queue(this, 'WebhooksQueue', {
            queueName: `ChatBooking-WebhooksQueue-${props.envName}`,
            visibilityTimeout: cdk.Duration.seconds(60), // Enough for processing
            deadLetterQueue: {
                queue: this.webhooksDLQ,
                maxReceiveCount: 3,
            },
        });

        // 3. Lambda Layer (Shared)
        const layerArn = ssm.StringParameter.valueForStringParameter(
            this, '/chatbooking/layers/python-layer-arn'
        );
        const sharedLayer = lambda.LayerVersion.fromLayerVersionArn(this, 'SharedLayer', layerArn);

        // Common Lambda Props
        const commonProps = {
            runtime: lambda.Runtime.PYTHON_3_11,
            timeout: cdk.Duration.seconds(30),
            memorySize: 256,
            logRetention: logs.RetentionDays.ONE_WEEK,
            layers: [sharedLayer],
            environment: {
                SUBSCRIPTIONS_TABLE: this.subscriptionsTable.tableName,
                TENANTS_TABLE: props.tenantsTable.tableName,
                LOG_LEVEL: 'INFO',
                MP_ACCESS_TOKEN: secretsmanager.Secret.fromSecretNameV2(this, 'MPSecret', 'ChatBooking/MercadoPago')
                    .secretValueFromJson('ACCESS_TOKEN').unsafeUnwrap(),
                MP_WEBHOOK_SECRET: secretsmanager.Secret.fromSecretNameV2(this, 'MPSecretVal', 'ChatBooking/MercadoPago')
                    .secretValueFromJson('WEBHOOK_SECRET').unsafeUnwrap(),
            },
        };

        // 4. Lambdas

        // A. Subscribe Handler
        this.subscribeFunction = new lambda.Function(this, 'SubscribeFunction', {
            ...commonProps,
            description: 'Handle new subscription creation',
            code: lambda.Code.fromAsset(path.join(backendPath, 'subscriptions/handlers')), // Assuming a new folder structure
            handler: 'subscribe.lambda_handler',
        });
        this.subscriptionsTable.grantReadWriteData(this.subscribeFunction);
        props.tenantsTable.grantReadData(this.subscribeFunction);

        // B. Downgrade Handler
        this.downgradeFunction = new lambda.Function(this, 'DowngradeFunction', {
            ...commonProps,
            description: 'Handle subscription downgrade scheduling',
            code: lambda.Code.fromAsset(path.join(backendPath, 'subscriptions/handlers')),
            handler: 'downgrade.lambda_handler',
        });
        this.subscriptionsTable.grantReadWriteData(this.downgradeFunction);

        // C. Webhook Ingestor (Public Endpoint)
        this.webhookIngestorFunction = new lambda.Function(this, 'WebhookIngestorFunction', {
            ...commonProps,
            description: 'Ingest Mercado Pago webhooks securely',
            code: lambda.Code.fromAsset(path.join(backendPath, 'subscriptions/handlers')),
            handler: 'webhook_ingestor.lambda_handler',
            environment: {
                ...commonProps.environment,
                QUEUE_URL: this.webhooksQueue.queueUrl,
            }
        });
        this.webhooksQueue.grantSendMessages(this.webhookIngestorFunction);

        // Add Function URL
        const webhookUrl = this.webhookIngestorFunction.addFunctionUrl({
            authType: lambda.FunctionUrlAuthType.NONE,
        });

        // D. Webhook Processor
        this.webhookProcessorFunction = new lambda.Function(this, 'WebhookProcessorFunction', {
            ...commonProps,
            description: 'Process webhook events from queue',
            code: lambda.Code.fromAsset(path.join(backendPath, 'subscriptions/handlers')),
            handler: 'webhook_processor.lambda_handler',
            events: [new (require('aws-cdk-lib/aws-lambda-event-sources').SqsEventSource)(this.webhooksQueue, {
                batchSize: 1, // Strict ordering ideally, but idempotency handles it
            })]
        });
        this.subscriptionsTable.grantReadWriteData(this.webhookProcessorFunction);
        props.tenantsTable.grantReadData(this.webhookProcessorFunction);

        // E. Subscription Worker (Scheduler Target)
        this.subscriptionWorkerFunction = new lambda.Function(this, 'SubscriptionWorkerFunction', {
            ...commonProps,
            description: 'Execute scheduled subscription tasks',
            code: lambda.Code.fromAsset(path.join(backendPath, 'subscriptions/workers')),
            handler: 'subscription_worker.lambda_handler',
        });
        this.subscriptionsTable.grantReadWriteData(this.subscriptionWorkerFunction);

        // F. List Invoices Handler
        this.listInvoicesFunction = new lambda.Function(this, 'ListInvoicesFunction', {
            ...commonProps,
            description: 'List tenant invoices',
            code: lambda.Code.fromAsset(path.join(backendPath, 'subscriptions/handlers')),
            handler: 'list_invoices.lambda_handler',
        });
        this.subscriptionsTable.grantReadData(this.listInvoicesFunction);

        // 5. IAM Role for EventBridge Scheduler
        const schedulerRole = new iam.Role(this, 'SchedulerRole', {
            assumedBy: new iam.ServicePrincipal('scheduler.amazonaws.com'),
        });

        // Grant Scheduler permission to invoke worker
        schedulerRole.addToPolicy(new iam.PolicyStatement({
            actions: ['lambda:InvokeFunction'],
            resources: [this.subscriptionWorkerFunction.functionArn],
        }));

        // Grant Worker permission to manage schedules (delete them on cancel)
        this.subscriptionWorkerFunction.addToRolePolicy(new iam.PolicyStatement({
            actions: ['scheduler:DeleteSchedule'],
            resources: ['*'], // Scope down if possible to specific group
        }));

        // Grant Subscribe/Downgrade handlers permission to create schedules
        const createSchedulePolicy = new iam.PolicyStatement({
            actions: ['scheduler:CreateSchedule'],
            resources: ['*'],
        });
        const passRolePolicy = new iam.PolicyStatement({
            actions: ['iam:PassRole'],
            resources: [schedulerRole.roleArn],
        });

        this.subscribeFunction.addToRolePolicy(createSchedulePolicy);
        this.subscribeFunction.addToRolePolicy(passRolePolicy);
        this.downgradeFunction.addToRolePolicy(createSchedulePolicy);
        this.downgradeFunction.addToRolePolicy(passRolePolicy);

        // Outputs
        new cdk.CfnOutput(this, 'SubscriptionsTableName', { value: this.subscriptionsTable.tableName });
        new cdk.CfnOutput(this, 'WebhookUrl', { value: webhookUrl.url });
        new cdk.CfnOutput(this, 'SchedulerRoleArn', { value: schedulerRole.roleArn });
    }
}
