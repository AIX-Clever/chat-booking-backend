#!/usr/bin/env node
import 'source-map-support/register';
import * as dotenv from 'dotenv';
dotenv.config(); // Load .env file
import * as cdk from 'aws-cdk-lib';
import { DatabaseStack } from '../lib/database-stack';
import { LambdaStack } from '../lib/lambda-stack';
import { AppSyncApiStack } from '../lib/appsync-api-stack';
import { AuthStack } from '../lib/auth-stack';
// import { VectorDatabaseStack } from '../lib/vector-database-stack';
import { AssetsStack } from '../lib/assets-stack';

/**
 * CDK App Entry Point
 * 
 * Instantiates and connects all infrastructure stacks:
 * 1. Database (DynamoDB tables)
 * 2. Lambda (Functions and layers)
 * 3. AppSync API (GraphQL API)
 * 4. Auth (Cognito User Pool)
 * 
 * Stack dependencies:
 * Lambda -> Database
 * AppSync -> Lambda
 * Auth (independent)
 */

const app = new cdk.App();

// Get environment from context
const env = app.node.tryGetContext('env') || 'dev';
const account = app.node.tryGetContext('account') || process.env.CDK_DEFAULT_ACCOUNT;
const region = app.node.tryGetContext('region') || process.env.CDK_DEFAULT_REGION || process.env.AWS_REGION;

// Common tags for all resources
const tags = {
  Project: 'ChatBooking',
  Environment: env,
  ManagedBy: 'CDK',
};

// Stack naming convention
const stackPrefix = `ChatBooking-${env}`;

// 1. Database Stack - Foundation
const databaseStack = new DatabaseStack(app, `${stackPrefix}-Database`, {
  env: { account, region },
  description: 'DynamoDB tables for Chat Booking SaaS',
  tags,
});



// 2. Auth Stack - Cognito for Admin Panel (Must be before Lambda)
const authStack = new AuthStack(app, `${stackPrefix}-Auth`, {
  env: { account, region },
  description: 'Cognito User Pool for Chat Booking Admin',
  tags,
});

// 2.5 Knowledge Base Stack - REMOVED for Cost Optimization (RDS + VPC)
// const vectorDbStack = new VectorDatabaseStack(app, `${stackPrefix}-KnowledgeBase`, {
//   env: { account, region },
//   description: 'Aurora Serverless v2 with pgvector for AI Knowledge Base',
//   tags,
// });

// 2.6 Assets Stack - S3 for User Uploads
const assetsStack = new AssetsStack(app, `${stackPrefix}-Assets`, {
  env: { account, region },
  description: 'S3 + CloudFront for Assets',
  tags,
  stage: env,
  domainName: process.env.MEDIA_DOMAIN_NAME,
  certificateArn: process.env.CERTIFICATE_ARN,
});

// 2.7 Subscription Stack - Billing & Payments (Secure)
import { SubscriptionStack } from '../lib/subscription-stack';
const subscriptionStack = new SubscriptionStack(app, `${stackPrefix}-Subscriptions`, {
  env: { account, region },
  description: 'SaaS Subscriptions Core (DynamoDB + SQS + Lambdas)',
  tags,
  tenantsTable: databaseStack.tenantsTable,
  userPool: authStack.userPool,
  envName: env,
});
subscriptionStack.addDependency(databaseStack);

// 2.8 WhatsApp Stack - Messaging Infrastructure
import { WhatsappStack } from '../lib/whatsapp-stack';
const whatsappStack = new WhatsappStack(app, `${stackPrefix}-Whatsapp`, {
  env: { account, region },
  description: 'Messaging Infrastructure (SNS + SQS) for WhatsApp',
  tags,
});

// 3. Backend Stack - Business Logic
const lambdaStack = new LambdaStack(app, `${stackPrefix}-Backend`, {
  env: { account, region },
  description: 'Lambda functions for Chat Booking Backend',
  tags,
  // vpc: vectorDbStack.vpc, // Removed
  // dbSecurityGroup: vectorDbStack.dbSecurityGroup, // Removed
  // dbSecret: vectorDbStack.dbSecret, // Removed
  // dbEndpoint: vectorDbStack.cluster.clusterArn, // Removed
  tenantsTable: databaseStack.tenantsTable,
  apiKeysTable: databaseStack.apiKeysTable,
  servicesTable: databaseStack.servicesTable,
  providersTable: databaseStack.providersTable,
  availabilityTable: databaseStack.availabilityTable,
  bookingsTable: databaseStack.bookingsTable,
  conversationsTable: databaseStack.conversationsTable,
  categoriesTable: databaseStack.categoriesTable,
  tenantUsageTable: databaseStack.tenantUsageTable,
  workflowsTable: databaseStack.workflowsTable,
  faqsTable: databaseStack.faqsTable,
  documentsTable: databaseStack.documentsTable,
  roomsTable: databaseStack.roomsTable,
  userRolesTable: databaseStack.userRolesTable,
  userPool: authStack.userPool,
  envName: env,
  assetsBucketName: assetsStack.assetsBucket.bucketName,
  subscriptionsTable: subscriptionStack.subscriptionsTable,
  clientsTable: databaseStack.clientsTable,
  clientAuditLogsTable: databaseStack.clientAuditLogsTable,
  dteFoliosTable: databaseStack.dteFoliosTable,
  whatsappMessagesTable: databaseStack.whatsappMessagesTable,
  whatsappNotificationTopic: whatsappStack.notificationTopic,
  whatsappSenderQueue: whatsappStack.senderQueue,
  waitingListTable: databaseStack.waitingListTable,
});
lambdaStack.addDependency(databaseStack);
lambdaStack.addDependency(subscriptionStack);
lambdaStack.addDependency(authStack);
lambdaStack.addDependency(whatsappStack);

// 4. AppSync API Stack - GraphQL Gateway
const appSyncApiStack = new AppSyncApiStack(app, `${stackPrefix}-AppSyncApi`, {
  env: { account, region },
  description: 'GraphQL API for Chat Booking SaaS',
  tags,
  domainName: process.env.API_DOMAIN_NAME,
  certificateArn: process.env.CERTIFICATE_ARN,
  authResolverFunction: lambdaStack.authResolverFunction,
  catalogFunction: lambdaStack.catalogFunction,
  availabilityFunction: lambdaStack.availabilityFunction,
  bookingFunction: lambdaStack.bookingFunction,
  chatAgentFunction: lambdaStack.chatAgentFunction,
  registerTenantFunction: lambdaStack.registerTenantFunction,
  updateTenantFunction: lambdaStack.updateTenantFunction,
  getTenantFunction: lambdaStack.getTenantFunction,
  getPublicProfileFunction: lambdaStack.getPublicProfileFunction,
  publicLinkStatusFunction: lambdaStack.publicLinkStatusFunction,
  metricsFunction: lambdaStack.metricsFunction,
  workflowManagerFunction: lambdaStack.workflowManagerFunction,
  faqManagerFunction: lambdaStack.faqManagerFunction,
  userManagementFunction: lambdaStack.userManagementFunction,
  presignFunction: lambdaStack.presignFunction,
  apiKeyManagerFunction: lambdaStack.apiKeyManagerFunction,
  subscribeFunction: subscriptionStack.subscribeFunction,
  downgradeFunction: subscriptionStack.downgradeFunction,
  listInvoicesFunction: subscriptionStack.listInvoicesFunction,
  checkPaymentStatusFunction: lambdaStack.checkPaymentStatusFunction,
  clientsFunction: lambdaStack.clientsFunction,
  supportManagerFunction: lambdaStack.supportManagerFunction,
  waitlistApiFunction: lambdaStack.waitlistApiFunction,
  userPool: authStack.userPool,
});
appSyncApiStack.addDependency(lambdaStack);
appSyncApiStack.addDependency(authStack);

// Add stack outputs summary
new cdk.CfnOutput(appSyncApiStack, 'DeploymentSummary', {
  value: JSON.stringify({
    environment: env,
    region,
    graphqlEndpoint: appSyncApiStack.api.graphqlUrl,
    userPoolId: authStack.userPool.userPoolId,
  }),
  description: 'Deployment summary',
});

// Synth the app
app.synth();
