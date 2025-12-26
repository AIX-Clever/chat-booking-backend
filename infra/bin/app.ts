#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { DatabaseStack } from '../lib/database-stack';
import { LambdaStack } from '../lib/lambda-stack';
import { AppSyncApiStack } from '../lib/appsync-api-stack';
import { AuthStack } from '../lib/auth-stack';
import { VectorDatabaseStack } from '../lib/vector-database-stack';

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
const region = app.node.tryGetContext('region') || process.env.CDK_DEFAULT_REGION || 'us-east-1';

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

// 2.5 Knowledge Base Stack - Aurora Serverless v2 + VPC (Private Network)
const vectorDbStack = new VectorDatabaseStack(app, `${stackPrefix}-KnowledgeBase`, {
  env: { account, region },
  description: 'Aurora Serverless v2 with pgvector for AI Knowledge Base',
  tags,
});

// 3. Backend Stack - Business Logic
const lambdaStack = new LambdaStack(app, `${stackPrefix}-BackendV3`, {
  env: { account, region },
  description: 'Lambda functions for Chat Booking Backend',
  tags,
  vpc: vectorDbStack.vpc,
  dbSecurityGroup: vectorDbStack.dbSecurityGroup,
  dbSecret: vectorDbStack.dbSecret,
  dbEndpoint: vectorDbStack.cluster.clusterArn, // For Data API, we pass the ARN
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
  userPool: authStack.userPool,
});
lambdaStack.addDependency(databaseStack);
lambdaStack.addDependency(authStack);
lambdaStack.addDependency(vectorDbStack);

// 4. AppSync API Stack - GraphQL Gateway
const appSyncApiStack = new AppSyncApiStack(app, `${stackPrefix}-AppSyncApiV2`, {
  env: { account, region },
  description: 'GraphQL API for Chat Booking SaaS',
  tags,
  authResolverFunction: lambdaStack.authResolverFunction,
  catalogFunction: lambdaStack.catalogFunction,
  availabilityFunction: lambdaStack.availabilityFunction,
  bookingFunction: lambdaStack.bookingFunction,
  chatAgentFunction: lambdaStack.chatAgentFunction,
  registerTenantFunction: lambdaStack.registerTenantFunction,
  updateTenantFunction: lambdaStack.updateTenantFunction,
  getTenantFunction: lambdaStack.getTenantFunction,
  metricsFunction: lambdaStack.metricsFunction,
  workflowManagerFunction: lambdaStack.workflowManagerFunction,
  faqManagerFunction: lambdaStack.faqManagerFunction,
  presignFunction: lambdaStack.presignFunction,
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
