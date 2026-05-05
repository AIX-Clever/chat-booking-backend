import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';

export interface DatabaseStackProps extends cdk.StackProps {
  envName?: string;
}

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
  public readonly roomAssignmentsTable: dynamodb.Table;
  public readonly userRolesTable: dynamodb.Table;
  public readonly clientsTable: dynamodb.Table;
  public readonly clientAuditLogsTable: dynamodb.Table;
  public readonly dteFoliosTable: dynamodb.Table;
  public readonly whatsappMessagesTable: dynamodb.Table;
  public readonly waitingListTable: dynamodb.Table;

  constructor(scope: Construct, id: string, props?: DatabaseStackProps) {
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
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,

    });

    // GSI: slug index for tenant lookup by URL slug (deployed 2026-01-22)
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
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,

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

    // GSI1: search index for API key lookup by hash (shared repo expects this)
    this.apiKeysTable.addGlobalSecondaryIndex({
      indexName: 'GSI1',
      partitionKey: {
        name: 'apiKeyHash',
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
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,

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
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,

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
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,

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
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,

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
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,

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
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,

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
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,

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
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,

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
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,

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
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,

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
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,

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

    // 13b. RoomAssignments Table — exclusive provider-room-day assignments
    this.roomAssignmentsTable = new dynamodb.Table(this, 'RoomAssignmentsTable', {
      tableName: 'ChatBooking-RoomAssignments',
      partitionKey: {
        name: 'pk',  // tenantId#roomId
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'sk',  // providerId
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // GSI: byProvider — query all room assignments for a given provider
    this.roomAssignmentsTable.addGlobalSecondaryIndex({
      indexName: 'byProvider',
      partitionKey: {
        name: 'providerPk',  // tenantId#providerId
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    new cdk.CfnOutput(this, 'RoomAssignmentsTableName', {
      value: this.roomAssignmentsTable.tableName,
      description: 'Room Assignments table name',
    });

    // 14. User Roles Table
    this.userRolesTable = new dynamodb.Table(this, 'UserRolesTable', {
      tableName: 'ChatBooking-UserRoles',
      partitionKey: {
        name: 'userId',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,

    });

    // GSI: tenantId index for listing all users in a tenant
    this.userRolesTable.addGlobalSecondaryIndex({
      indexName: 'byTenant',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'createdAt',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    new cdk.CfnOutput(this, 'UserRolesTableName', {
      value: this.userRolesTable.tableName,
      description: 'User Roles table name',
    });

    // 15. Clients Table (Client File)
    this.clientsTable = new dynamodb.Table(this, 'ClientsTable', {
      tableName: 'ChatBooking-Clients',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'id',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
    });

    // GSI: email-index for client lookup by email
    this.clientsTable.addGlobalSecondaryIndex({
      indexName: 'email-index',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'email',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI: tax-id-index for client lookup by identifier (RUT/CPF/Passport)
    this.clientsTable.addGlobalSecondaryIndex({
      indexName: 'tax-id-index',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'identifierValue',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // 16. Client Audit Logs Table (Trazabilidad)
    this.clientAuditLogsTable = new dynamodb.Table(this, 'ClientAuditLogsTable', {
      tableName: 'ChatBooking-ClientAuditLogs',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'clientIdAndTimestamp', // Format: {clientId}#{timestamp}
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // 17. DTE Folios Table (CAF Management)
    this.dteFoliosTable = new dynamodb.Table(this, 'DTEFoliosTable', {
      tableName: 'ChatBooking-DTEFolios',
      partitionKey: {
        name: 'tenantId_tipoDte', // Format: {tenantId}#{tipoDte}
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // 18. Whatsapp Messages Table
    this.whatsappMessagesTable = new dynamodb.Table(this, 'WhatsappMessagesTable', {
      tableName: 'ChatBooking-WhatsappMessages',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'messageId',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
      timeToLiveAttribute: 'ttl', // Auto-cleanup old messages
    });

    // GSI: messageId index for webhook lookups
    this.whatsappMessagesTable.addGlobalSecondaryIndex({
      indexName: 'messageId-index',
      partitionKey: {
        name: 'messageId',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI: status index for querying messages by status
    this.whatsappMessagesTable.addGlobalSecondaryIndex({
      indexName: 'status-index',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'status',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI: bookingId index for querying messages related to a booking
    this.whatsappMessagesTable.addGlobalSecondaryIndex({
      indexName: 'bookingId-index',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'bookingId',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI: destinationPhone index for querying messages sent to a phone
    this.whatsappMessagesTable.addGlobalSecondaryIndex({
      indexName: 'destinationPhone-index',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'destinationPhone',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    new cdk.CfnOutput(this, 'ClientAuditLogsTableName', {
      value: this.clientAuditLogsTable.tableName,
      description: 'Client Audit Logs table name',
    });

    new cdk.CfnOutput(this, 'DTEFoliosTableName', {
      value: this.dteFoliosTable.tableName,
      description: 'DTE Folios table name',
    });

    new cdk.CfnOutput(this, 'WhatsappMessagesTableName', {
      value: this.whatsappMessagesTable.tableName,
      description: 'Whatsapp Messages table name',
    });

    // WaitingList Table
    this.waitingListTable = new dynamodb.Table(this, 'WaitingListTable', {
      tableName: 'ChatBooking-WaitingList',
      partitionKey: {
        name: 'tenantId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'waitingListId',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
      timeToLiveAttribute: 'ttl',
    });

    // GSI: serviceId-createdAt for FIFO waitlist queries per service
    this.waitingListTable.addGlobalSecondaryIndex({
      indexName: 'serviceId-createdAt-index',
      partitionKey: {
        name: 'tenantId_serviceId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'createdAt',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    new cdk.CfnOutput(this, 'WaitingListTableName', {
      value: this.waitingListTable.tableName,
      description: 'Waiting List table name',
    });

    if (props?.envName) {
      new ssm.StringParameter(this, 'TenantsTableNameParam', {
        parameterName: `/chatbooking/${props.envName}/tenants-table-name`,
        stringValue: this.tenantsTable.tableName,
      });

      new ssm.StringParameter(this, 'DteFoliosTableNameParam', {
        parameterName: `/chatbooking/${props.envName}/dte-folios-table-name`,
        stringValue: this.dteFoliosTable.tableName,
      });
    }
  }
}
