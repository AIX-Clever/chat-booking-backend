import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { Construct } from 'constructs';

/**
 * Database Stack
 * 
 * Creates all DynamoDB tables for the multi-tenant SaaS booking system
 * 
 * Tables:
 * 1. Tenants - Tenant accounts
 * 2. ApiKeys - API keys for widget authentication
 * 3. Services - Service catalog
 * 4. Providers - Service providers/professionals
 * 5. ProviderAvailability - Provider schedules
 * 6. Bookings - Booking records
 * 7. Conversations - Chat conversations
 */
export class DatabaseStack extends cdk.Stack {
  public readonly tenantsTable: dynamodb.Table;
  public readonly apiKeysTable: dynamodb.Table;
  public readonly servicesTable: dynamodb.Table;
  public readonly providersTable: dynamodb.Table;
  public readonly availabilityTable: dynamodb.Table;
  public readonly bookingsTable: dynamodb.Table;
  public readonly conversationsTable: dynamodb.Table;
  public readonly categoriesTable: dynamodb.Table;
  public readonly tenantUsageTable: dynamodb.Table;
  public readonly workflowsTable: dynamodb.Table;
  public readonly faqsTable: dynamodb.Table;
  public readonly documentsTable: dynamodb.Table;
  public readonly roomsTable: dynamodb.Table;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // 1. Tenants Table
    this.tenantsTable = new dynamodb.Table(this, 'TenantsTable', {
      tableName: 'ChatBooking-Tenants',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
    });

    // GSI: slug index for tenant lookup by URL slug
    this.tenantsTable.addGlobalSecondaryIndex({
      indexName: 'slug-index',
      partitionKey: {
        name: 'slug',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // 2. ApiKeys Table
    this.apiKeysTable = new dynamodb.Table(this, 'ApiKeysTable', {
      tableName: 'ChatBooking-ApiKeys',
      partitionKey: {
        name: 'apiKeyHash',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
    });

    // GSI: tenantId index for listing tenant's API keys
    this.apiKeysTable.addGlobalSecondaryIndex({
      indexName: 'tenantId-index',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // 3. Services Table
    this.servicesTable = new dynamodb.Table(this, 'ServicesTable', {
      tableName: 'ChatBooking-Services',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'serviceId',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
    });

    // GSI: category index for service search by category
    this.servicesTable.addGlobalSecondaryIndex({
      indexName: 'category-index',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'category',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // 4. Providers Table
    this.providersTable = new dynamodb.Table(this, 'ProvidersTable', {
      tableName: 'ChatBooking-Providers',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'providerId',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
    });

    // GSI: serviceId index for provider lookup by service
    this.providersTable.addGlobalSecondaryIndex({
      indexName: 'serviceId-index',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'serviceIds',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // 5. ProviderAvailability Table
    this.availabilityTable = new dynamodb.Table(this, 'AvailabilityTable', {
      tableName: 'ChatBooking-ProviderAvailability',
      partitionKey: {
        name: 'tenantId_providerId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'dayOfWeek',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
    });

    // 6. Bookings Table
    this.bookingsTable = new dynamodb.Table(this, 'BookingsTable', {
      tableName: 'ChatBooking-Bookings',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'bookingId',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
    });

    // GSI: providerId-start index for provider's bookings by date
    this.bookingsTable.addGlobalSecondaryIndex({
      indexName: 'providerId-start-index',
      partitionKey: {
        name: 'tenantId_providerId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'start',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI: clientEmail index for client's booking history
    this.bookingsTable.addGlobalSecondaryIndex({
      indexName: 'clientEmail-index',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'clientEmail',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI: conversationId index for booking lookup by conversation
    this.bookingsTable.addGlobalSecondaryIndex({
      indexName: 'conversationId-index',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'conversationId',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // 7. Conversations Table
    this.conversationsTable = new dynamodb.Table(this, 'ConversationsTable', {
      tableName: 'ChatBooking-Conversations',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'conversationId',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
    });

    // GSI: state index for conversation queries by state
    this.conversationsTable.addGlobalSecondaryIndex({
      indexName: 'state-index',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'state',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // 8. Categories Table
    this.categoriesTable = new dynamodb.Table(this, 'CategoriesTable', {
      tableName: 'ChatBooking-Categories',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'categoryId',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
    });

    // 9. TenantUsage Table - Pre-aggregated metrics for dashboard
    this.tenantUsageTable = new dynamodb.Table(this, 'TenantUsageTable', {
      tableName: 'ChatBooking-TenantUsage',
      partitionKey: {
        name: 'PK',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'SK',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
      timeToLiveAttribute: 'ttl', // Auto-cleanup old metrics
    });

    // 10. Workflows Table
    this.workflowsTable = new dynamodb.Table(this, 'WorkflowsTable', {
      tableName: 'ChatBooking-Workflows',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'workflowId',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
    });

    // 11. FAQs Table
    this.faqsTable = new dynamodb.Table(this, 'FAQsTable', {
      tableName: 'ChatBooking-FAQs',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'faqId',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
    });

    // 12. Documents Table (Knowledge Base)
    this.documentsTable = new dynamodb.Table(this, 'DocumentsTable', {
      tableName: 'ChatBooking-Documents',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'documentId',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
    });

    // Output table names and ARNs
    new cdk.CfnOutput(this, 'TenantsTableName', {
      value: this.tenantsTable.tableName,
      description: 'Tenants table name',
    });

    new cdk.CfnOutput(this, 'ApiKeysTableName', {
      value: this.apiKeysTable.tableName,
      description: 'API Keys table name',
    });

    new cdk.CfnOutput(this, 'ServicesTableName', {
      value: this.servicesTable.tableName,
      description: 'Services table name',
    });

    new cdk.CfnOutput(this, 'ProvidersTableName', {
      value: this.providersTable.tableName,
      description: 'Providers table name',
    });

    new cdk.CfnOutput(this, 'AvailabilityTableName', {
      value: this.availabilityTable.tableName,
      description: 'Provider Availability table name',
    });

    new cdk.CfnOutput(this, 'BookingsTableName', {
      value: this.bookingsTable.tableName,
      description: 'Bookings table name',
    });

    new cdk.CfnOutput(this, 'ConversationsTableName', {
      value: this.conversationsTable.tableName,
      description: 'Conversations table name',
    });

    new cdk.CfnOutput(this, 'CategoriesTableName', {
      value: this.categoriesTable.tableName,
      description: 'Categories table name',
    });

    new cdk.CfnOutput(this, 'TenantUsageTableName', {
      value: this.tenantUsageTable.tableName,
      description: 'Tenant Usage (metrics) table name',
    });

    new cdk.CfnOutput(this, 'WorkflowsTableName', {
      value: this.workflowsTable.tableName,
      description: 'Workflows table name',
    });

    new cdk.CfnOutput(this, 'FAQsTableName', {
      value: this.faqsTable.tableName,
      description: 'FAQs table name',
    });

    new cdk.CfnOutput(this, 'DocumentsTableName', {
      value: this.documentsTable.tableName,
      description: 'Documents table name',
    });

    // 13. Rooms Table
    this.roomsTable = new dynamodb.Table(this, 'RoomsTable', {
      tableName: 'ChatBooking-Rooms',
      partitionKey: {
        name: 'roomId',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
    });

    // GSI: tenantId index for listing by tenant
    this.roomsTable.addGlobalSecondaryIndex({
      indexName: 'byTenant',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    new cdk.CfnOutput(this, 'RoomsTableName', {
      value: this.roomsTable.tableName,
      description: 'Rooms table name',
    });
  }
}
