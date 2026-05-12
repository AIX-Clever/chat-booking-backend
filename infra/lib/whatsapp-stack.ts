import * as cdk from 'aws-cdk-lib';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as scheduler from 'aws-cdk-lib/aws-scheduler';
import * as subscriptions from 'aws-cdk-lib/aws-sns-subscriptions';
import { Construct } from 'constructs';

export class WhatsappStack extends cdk.Stack {
    public readonly notificationTopic: sns.Topic;
    public readonly senderQueue: sqs.Queue;
    public readonly dlq: sqs.Queue;
    public readonly schedulerGroup: scheduler.CfnScheduleGroup;
    public readonly schedulerRole: iam.Role;

    constructor(scope: Construct, id: string, props?: cdk.StackProps) {
        super(scope, id, props);

        // 1. Dead Letter Queue for failed messages that exhaust retries
        this.dlq = new sqs.Queue(this, 'WhatsappSenderDLQ', {
            queueName: 'ChatBooking-WhatsappSenderDLQ',
            retentionPeriod: cdk.Duration.days(14),
        });

        // 2. Main SQS Queue for processing WhatsApp outbound messages
        this.senderQueue = new sqs.Queue(this, 'WhatsappSenderQueue', {
            queueName: 'ChatBooking-WhatsappSenderQueue',
            visibilityTimeout: cdk.Duration.seconds(30),
            retentionPeriod: cdk.Duration.days(4),
            deadLetterQueue: {
                queue: this.dlq,
                maxReceiveCount: 3,
            },
        });

        // 3. SNS Topic for publishing WhatsApp notification events
        this.notificationTopic = new sns.Topic(this, 'WhatsappNotificationTopic', {
            topicName: 'ChatBooking-WhatsappNotificationTopic',
            displayName: 'WhatsApp Outbound Notifications Topic',
        });

        // 4. Subscribe the SQS queue to the SNS topic (for whatsapp_sender)
        // Filter to only WHATSAPP_SEND events — BOOKING_CONFIRMED goes to scheduler Lambdas only
        this.notificationTopic.addSubscription(new subscriptions.SqsSubscription(this.senderQueue, {
            rawMessageDelivery: true,
            filterPolicy: {
                event_type: sns.SubscriptionFilter.stringFilter({ allowlist: ['WHATSAPP_SEND'] }),
            },
        }));

        // 5. EventBridge Scheduler group — holds all per-booking one-time schedules
        this.schedulerGroup = new scheduler.CfnScheduleGroup(this, 'WhatsappSchedulesGroup', {
            name: 'ChatBooking-WhatsappSchedules',
        });

        // 6. IAM Role that EventBridge Scheduler uses to publish to SNS
        this.schedulerRole = new iam.Role(this, 'WhatsappSchedulerSnsRole', {
            roleName: 'ChatBooking-WhatsappSchedulerSnsRole',
            assumedBy: new iam.ServicePrincipal('scheduler.amazonaws.com'),
            description: 'Allows EventBridge Scheduler to publish timed reminders to the WhatsApp SNS topic',
        });
        this.notificationTopic.grantPublish(this.schedulerRole);

        // Outputs
        new cdk.CfnOutput(this, 'WhatsappNotificationTopicArn', {
            value: this.notificationTopic.topicArn,
            description: 'ARN of the SNS Topic for WhatsApp notifications',
        });
        new cdk.CfnOutput(this, 'WhatsappSenderQueueUrl', {
            value: this.senderQueue.queueUrl,
            description: 'URL of the SQS Queue for WhatsApp sending',
        });
        new cdk.CfnOutput(this, 'WhatsappSchedulerGroupName', {
            value: this.schedulerGroup.name!,
            description: 'Name of the EventBridge Scheduler group for WhatsApp reminders',
        });
        new cdk.CfnOutput(this, 'WhatsappSchedulerRoleArn', {
            value: this.schedulerRole.roleArn,
            description: 'ARN of the IAM role used by EventBridge Scheduler to publish to SNS',
        });
    }
}
