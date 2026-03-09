import * as cdk from 'aws-cdk-lib';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as subscriptions from 'aws-cdk-lib/aws-sns-subscriptions';
import { Construct } from 'constructs';

export class WhatsappStack extends cdk.Stack {
    public readonly notificationTopic: sns.Topic;
    public readonly senderQueue: sqs.Queue;
    public readonly dlq: sqs.Queue;

    constructor(scope: Construct, id: string, props?: cdk.StackProps) {
        super(scope, id, props);

        // 1. Dead Letter Queue for failed messages that exhaust retries
        this.dlq = new sqs.Queue(this, 'WhatsappSenderDLQ', {
            queueName: 'ChatBooking-WhatsappSenderDLQ',
            retentionPeriod: cdk.Duration.days(14), // Max retention for manual review
        });

        // 2. Main SQS Queue for processing WhatsApp outbound messages
        this.senderQueue = new sqs.Queue(this, 'WhatsappSenderQueue', {
            queueName: 'ChatBooking-WhatsappSenderQueue',
            visibilityTimeout: cdk.Duration.seconds(30), // Match Lambda timeout
            retentionPeriod: cdk.Duration.days(4), // Standard retention
            deadLetterQueue: {
                queue: this.dlq,
                maxReceiveCount: 3, // Retry 3 times before moving to DLQ
            },
        });

        // 3. SNS Topic for publishing WhatsApp notification events
        this.notificationTopic = new sns.Topic(this, 'WhatsappNotificationTopic', {
            topicName: 'ChatBooking-WhatsappNotificationTopic',
            displayName: 'WhatsApp Outbound Notifications Topic',
        });

        // 4. Subscribe the SQS queue to the SNS topic
        this.notificationTopic.addSubscription(new subscriptions.SqsSubscription(this.senderQueue, {
            rawMessageDelivery: true, // Deliver raw payload to SQS without SNS metadata formatting
        }));

        // Outputs
        new cdk.CfnOutput(this, 'WhatsappNotificationTopicArn', {
            value: this.notificationTopic.topicArn,
            description: 'ARN of the SNS Topic for WhatsApp notifications',
        });

        new cdk.CfnOutput(this, 'WhatsappSenderQueueUrl', {
            value: this.senderQueue.queueUrl,
            description: 'URL of the SQS Queue for WhatsApp sending',
        });
    }
}
