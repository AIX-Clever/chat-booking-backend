import * as cdk from 'aws-cdk-lib';
import * as appsync from 'aws-cdk-lib/aws-appsync';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { Construct } from 'constructs';
import * as path from 'path';
import * as fs from 'fs';

/**
 * AppSync API Stack
 * 
 * Creates GraphQL API with:
 * - Complete schema for booking system
 * - API Key authorization for widget
 * - Cognito authorization for admin (placeholder)
 * - Lambda resolvers for all operations
 */

interface AppSyncApiStackProps extends cdk.StackProps {
  authResolverFunction: lambda.IFunction;
  catalogFunction: lambda.IFunction;
  availabilityFunction: lambda.IFunction;
  bookingFunction: lambda.IFunction;
  chatAgentFunction: lambda.IFunction;
  registerTenantFunction: lambda.IFunction;
  updateTenantFunction: lambda.IFunction;
  getTenantFunction: lambda.IFunction;
  metricsFunction: lambda.IFunction;
  workflowManagerFunction: lambda.IFunction;
  faqManagerFunction: lambda.IFunction;
  presignFunction: lambda.IFunction;
  userPool: cdk.aws_cognito.IUserPool;
}

export class AppSyncApiStack extends cdk.Stack {
  public readonly api: appsync.GraphqlApi;
  public readonly apiKey: string;

  constructor(scope: Construct, id: string, props: AppSyncApiStackProps) {
    super(scope, id, props);

    // GraphQL Schema
    const schema = this.buildSchema();

    // Create AppSync API
    this.api = new appsync.GraphqlApi(this, 'ChatBookingApi', {
      name: 'ChatBookingGraphQLApi',
      schema: appsync.SchemaFile.fromAsset(this.createSchemaFile(schema)),
      authorizationConfig: {
        defaultAuthorization: {
          authorizationType: appsync.AuthorizationType.LAMBDA,
          lambdaAuthorizerConfig: {
            handler: props.authResolverFunction,
            resultsCacheTtl: cdk.Duration.minutes(5),
          },
        },
        additionalAuthorizationModes: [
          {
            authorizationType: appsync.AuthorizationType.USER_POOL,
            userPoolConfig: {
              userPool: props.userPool,
            },
          },
          {
            authorizationType: appsync.AuthorizationType.API_KEY,
            apiKeyConfig: {
              expires: cdk.Expiration.after(cdk.Duration.days(365)),
              description: 'API Key for internal/testing',
            },
          },
        ],
      },
      xrayEnabled: true,
      logConfig: {
        fieldLogLevel: appsync.FieldLogLevel.ERROR,
        excludeVerboseContent: false,
      },
    });

    // Create Lambda data sources
    const catalogDataSource = this.api.addLambdaDataSource(
      'CatalogDataSource',
      props.catalogFunction
    );

    const availabilityDataSource = this.api.addLambdaDataSource(
      'AvailabilityDataSource',
      props.availabilityFunction
    );

    const bookingDataSource = this.api.addLambdaDataSource(
      'BookingDataSource',
      props.bookingFunction
    );

    const chatAgentDataSource = this.api.addLambdaDataSource(
      'ChatAgentDataSource',
      props.chatAgentFunction
    );

    const registerTenantDataSource = this.api.addLambdaDataSource(
      'RegisterTenantDataSource',
      props.registerTenantFunction
    );

    const updateTenantDataSource = this.api.addLambdaDataSource(
      'UpdateTenantDataSource',
      props.updateTenantFunction
    );

    const getTenantDataSource = this.api.addLambdaDataSource(
      'GetTenantDataSource',
      props.getTenantFunction
    );

    const metricsDataSource = this.api.addLambdaDataSource(
      'MetricsDataSource',
      props.metricsFunction
    );

    const workflowManagerDataSource = this.api.addLambdaDataSource(
      'WorkflowManagerDataSource',
      props.workflowManagerFunction
    );

    const faqManagerDataSource = this.api.addLambdaDataSource(
      'FaqManagerDataSource',
      props.faqManagerFunction
    );

    const userManagementDataSource = this.api.addLambdaDataSource(
      'UserManagementDataSource',
      props.userManagementFunction
    );

    const presignDataSource = this.api.addLambdaDataSource(
      'PresignDataSource',
      props.presignFunction
    );

    // Create resolvers
    this.createResolvers(
      catalogDataSource,
      availabilityDataSource,
      bookingDataSource,
      chatAgentDataSource,
      registerTenantDataSource,
      updateTenantDataSource,
      getTenantDataSource,
      metricsDataSource,
      workflowManagerDataSource,
      faqManagerDataSource,
      presignDataSource
    );

    // Outputs
    new cdk.CfnOutput(this, 'GraphQLApiUrl', {
      value: this.api.graphqlUrl,
      description: 'GraphQL API endpoint',
    });

    new cdk.CfnOutput(this, 'GraphQLApiId', {
      value: this.api.apiId,
      description: 'GraphQL API ID',
    });

    new cdk.CfnOutput(this, 'GraphQLApiKey', {
      value: this.api.apiKey || 'N/A',
      description: 'GraphQL API Key (for testing)',
    });
  }

  private buildSchema(): string {
    return `
# Scalars
scalar AWSDateTime
scalar AWSJSON

# Enums
enum BookingStatus {
  PENDING
  CONFIRMED
  CANCELLED
  NO_SHOW
}

enum PaymentStatus {
  NONE
  PENDING
  PAID
  FAILED
}

enum ConversationState {
  INIT
  SERVICE_PENDING
  SERVICE_SELECTED
  PROVIDER_PENDING
  PROVIDER_SELECTED
  SLOT_PENDING
  CONFIRM_PENDING
  BOOKING_CONFIRMED
}

enum LocationType {
  ONLINE
  PHYSICAL
}

# Types - Tenant
type Room @aws_api_key @aws_cognito_user_pools {
  roomId: ID!
  tenantId: ID!
  name: String!
  description: String
  capacity: Int!
  status: String!
  metadata: AWSJSON
  createdAt: AWSDateTime!
  updatedAt: AWSDateTime!
}

enum TenantStatus {
  ACTIVE
  SUSPENDED
  CANCELLED
}

enum TenantPlan {
  LITE
  PRO
  BUSINESS
  ENTERPRISE
}

type Tenant @aws_api_key @aws_cognito_user_pools {
  tenantId: ID!
  name: String!
  slug: String!
  status: TenantStatus!
  plan: TenantPlan!
  ownerUserId: String!
  billingEmail: String!
  settings: AWSJSON
  createdAt: AWSDateTime!
  updatedAt: AWSDateTime!
}

type ApiKey {
  apiKey: String!
  tenantId: ID!
  status: String!
  createdAt: AWSDateTime!
  expiresAt: AWSDateTime!
}

# User Management Types
type TenantUser @aws_cognito_user_pools {
  userId: ID!
  tenantId: ID!
  email: String!
  name: String
  role: UserRole!
  status: UserStatus!
  createdAt: AWSDateTime!
  lastLogin: AWSDateTime
}

enum UserRole {
  OWNER
  ADMIN
  USER
}

enum UserStatus {
  ACTIVE
  INACTIVE
  PENDING_INVITATION
}

type FAQ @aws_api_key @aws_cognito_user_pools {
  faqId: ID!
  tenantId: ID!
  question: String!
  answer: String!
  category: String!
  active: Boolean!
}

# Types - Dashboard Metrics
type DashboardSummary @aws_cognito_user_pools {
  revenue: Float!
  bookings: Int!
  messages: Int!
  tokensIA: Int!
  conversionsChat: Int!
  aiResponses: Int!
  conversionRate: Float!
  autoAttendanceRate: Float!
}

type DailyMetric @aws_cognito_user_pools {
  date: String!
  bookings: Int!
  messages: Int!
}

type TopService @aws_cognito_user_pools {
  serviceId: ID!
  name: String!
  bookings: Int!
}

type TopProvider @aws_cognito_user_pools {
  providerId: ID!
  name: String!
  bookings: Int!
}

type BookingStatusCounts @aws_cognito_user_pools {
  CONFIRMED: Int!
  PENDING: Int!
  CANCELLED: Int!
  NO_SHOW: Int!
}

type MetricError @aws_cognito_user_pools {
  type: String!
  count: Int!
  lastOccurred: String
}

type DashboardMetrics @aws_cognito_user_pools {
  period: String!
  summary: DashboardSummary!
  daily: [DailyMetric!]!
  topServices: [TopService!]!
  topProviders: [TopProvider!]!
  bookingStatus: BookingStatusCounts!
  errors: [MetricError!]!
}

type PlanUsage @aws_cognito_user_pools {
  messages: Int!
  bookings: Int!
  tokensIA: Int!
}

# Types - Catalog
type Category @aws_api_key @aws_cognito_user_pools {
  categoryId: ID!
  tenantId: ID!
  name: String!
  description: String
  isActive: Boolean!
  displayOrder: Int
  metadata: AWSJSON
  createdAt: AWSDateTime!
  updatedAt: AWSDateTime!
}

type Service @aws_api_key @aws_cognito_user_pools {
  serviceId: ID!
  name: String!
  description: String
  category: String!
  durationMinutes: Int!
  price: Float
  available: Boolean!
  requiredRoomIds: [ID]
  locationType: [LocationType]
}

type Provider @aws_api_key @aws_cognito_user_pools {
  providerId: ID!
  name: String!
  bio: String
  serviceIds: [ID!]!
  timezone: String!
  metadata: AWSJSON
  available: Boolean!
}

# Types - Availability
type TimeSlot @aws_api_key @aws_cognito_user_pools {
  providerId: ID!
  serviceId: ID!
  start: AWSDateTime!
  end: AWSDateTime!
  isAvailable: Boolean!
}

type TimeRange @aws_api_key @aws_cognito_user_pools {
  startTime: String!
  endTime: String!
}

type ProviderAvailability @aws_cognito_user_pools {
  providerId: ID!
  dayOfWeek: String!
  timeRanges: [TimeRange!]!
  breaks: [TimeRange!]
  exceptions: [String!]
}

# Types - Bookings
type Booking @aws_api_key @aws_cognito_user_pools {
  bookingId: ID!
  tenantId: ID!
  serviceId: ID!
  providerId: ID!
  start: AWSDateTime!
  end: AWSDateTime!
  status: BookingStatus!
  clientName: String!
  clientEmail: String!
  clientPhone: String
  notes: String
  conversationId: ID
  paymentStatus: PaymentStatus!
  totalAmount: Float!
  createdAt: AWSDateTime!
  updatedAt: AWSDateTime!
}

# Types - Chat
type Message @aws_api_key {
  role: String!
  content: String!
  type: String!
  timestamp: String!
}

type Conversation @aws_api_key {
  conversationId: ID!
  tenantId: ID!
  state: ConversationState!
  context: AWSJSON
  messages: [Message!]!
  channel: String!
  metadata: AWSJSON
  createdAt: AWSDateTime!
  updatedAt: AWSDateTime!
}

type ChatResponse @aws_api_key {
  conversation: Conversation!
  response: AWSJSON!
}

# Types - Workflow
type WorkflowStep @aws_cognito_user_pools {
  stepId: String!
  type: String!
  content: AWSJSON
  next: String
}

type Workflow @aws_cognito_user_pools {
  workflowId: ID!
  tenantId: ID!
  name: String!
  description: String
  isActive: Boolean!
  steps: AWSJSON! # JSON object with map of steps
  metadata: AWSJSON
  createdAt: AWSDateTime!
  updatedAt: AWSDateTime!
}


# Inputs - Tenant
input RegisterTenantInput {
  companyName: String!
  email: String!
  password: String!
}

input CreateRoomInput {
  name: String!
  description: String
  capacity: Int
  status: String
  metadata: AWSJSON
}

input UpdateRoomInput {
  roomId: ID!
  name: String
  description: String
  capacity: Int
  status: String
  metadata: AWSJSON
}

input UpdateTenantInput {
  name: String
  billingEmail: String
  settings: AWSJSON
}

# Inputs - FAQs
input CreateFAQInput {
  question: String!
  answer: String!
  category: String
  active: Boolean
}

input UpdateFAQInput {
  faqId: ID!
  question: String
  answer: String
  category: String
  active: Boolean
}

# Inputs - Catalog
input CreateCategoryInput {
  name: String!
  description: String
  isActive: Boolean
  displayOrder: Int
  metadata: AWSJSON
}

input UpdateCategoryInput {
  categoryId: ID!
  name: String
  description: String
  isActive: Boolean
  displayOrder: Int
  metadata: AWSJSON
}

input CreateServiceInput {
  name: String!
  description: String
  category: String!
  durationMinutes: Int!
  price: Float
}

input UpdateServiceInput {
  serviceId: ID!
  name: String
  description: String
  category: String
  durationMinutes: Int
  price: Float
  available: Boolean
}

input CreateProviderInput {
  name: String!
  bio: String
  serviceIds: [ID!]!
  timezone: String!
  metadata: AWSJSON
}

input UpdateProviderInput {
  providerId: ID!
  name: String
  bio: String
  serviceIds: [ID!]
  timezone: String
  metadata: AWSJSON
  available: Boolean
}

# Inputs - Availability
input GetAvailableSlotsInput {
  serviceId: ID!
  providerId: ID!
  from: AWSDateTime!
  to: AWSDateTime!
}

input TimeRangeInput {
  startTime: String!
  endTime: String!
}

input SetAvailabilityInput {
  providerId: ID!
  dayOfWeek: String!
  timeRanges: [TimeRangeInput!]!
  breaks: [TimeRangeInput!]
}

input SetExceptionsInput {
  providerId: ID!
  exceptions: [String!]!
}

type ProviderExceptions @aws_cognito_user_pools {
  providerId: ID!
  exceptions: [String!]!
}

# Inputs - Bookings
input CreateBookingInput {
  serviceId: ID!
  providerId: ID!
  start: AWSDateTime!
  end: AWSDateTime!
  clientName: String!
  clientEmail: String!
  clientPhone: String
  notes: String
  conversationId: ID
}

input ConfirmBookingInput {
  bookingId: ID!
  tenantId: ID
}

input CancelBookingInput {
  bookingId: ID!
  reason: String
  tenantId: ID
}

input GetBookingInput {
  bookingId: ID!
}

input ListBookingsByProviderInput {
  providerId: ID!
  startDate: AWSDateTime!
  endDate: AWSDateTime!
}

input ListBookingsByClientInput {
  clientEmail: String!
}

input GetBookingByConversationInput {
  conversationId: ID!
}

# Inputs - Chat
input StartConversationInput {
  channel: String
  metadata: AWSJSON
}

input SendMessageInput {
  conversationId: ID!
  message: String!
  messageType: String
  userData: AWSJSON
}

input ConfirmBookingFromConversationInput {
  conversationId: ID!
}

input GetConversationInput {
  conversationId: ID!
}

# Inputs - Workflow
input CreateWorkflowInput {
  name: String!
  description: String
  steps: AWSJSON!
  metadata: AWSJSON
  isActive: Boolean
}

input UpdateWorkflowInput {
  workflowId: ID!
  name: String
  description: String
  steps: AWSJSON
  metadata: AWSJSON
  isActive: Boolean
}

# User Management Inputs
input InviteUserInput {
  email: String!
  name: String
  role: UserRole!
}

input UpdateUserRoleInput {
  userId: ID!
  role: UserRole!
}

# Queries
type Query {
  # Catalog
  listCategories(activeOnly: Boolean): [Category!]! @aws_api_key @aws_cognito_user_pools
  searchServices(text: String, availableOnly: Boolean): [Service!]! @aws_api_key @aws_cognito_user_pools
  getService(serviceId: ID!): Service @aws_api_key @aws_cognito_user_pools
  listProviders: [Provider!]! @aws_api_key @aws_cognito_user_pools
  listProvidersByService(serviceId: ID!): [Provider!]! @aws_api_key @aws_cognito_user_pools

  listRooms: [Room!]! @aws_cognito_user_pools
  getRoom(roomId: ID!): Room @aws_cognito_user_pools
  
  # Availability
  getAvailableSlots(input: GetAvailableSlotsInput!): [TimeSlot!]! @aws_api_key @aws_cognito_user_pools
  getProviderAvailability(providerId: ID!): [ProviderAvailability!]! @aws_cognito_user_pools
  
  # Bookings
  getBooking(input: GetBookingInput!): Booking @aws_api_key @aws_cognito_user_pools
  listBookingsByProvider(input: ListBookingsByProviderInput!): [Booking!]! @aws_cognito_user_pools
  listBookingsByClient(input: ListBookingsByClientInput!): [Booking!]! @aws_cognito_user_pools
  getBookingByConversation(input: GetBookingByConversationInput!): Booking @aws_api_key @aws_cognito_user_pools
  
  # Chat
  getConversation(input: GetConversationInput!): Conversation @aws_api_key @aws_cognito_user_pools
  getTenant(tenantId: ID): Tenant @aws_api_key @aws_cognito_user_pools
  listFAQs: [FAQ!]! @aws_api_key @aws_cognito_user_pools
  
  # Workflow (Admin)
  listWorkflows: [Workflow!]! @aws_cognito_user_pools
  getWorkflow(workflowId: ID!): Workflow @aws_cognito_user_pools

  # Dashboard Metrics (Admin)
  getDashboardMetrics: DashboardMetrics @aws_cognito_user_pools
  getPlanUsage: PlanUsage @aws_cognito_user_pools

  # User Management (Admin)
  listTenantUsers: [TenantUser!]! @aws_cognito_user_pools
  getTenantUser(userId: ID!): TenantUser @aws_cognito_user_pools
}

# Mutations
type Mutation {
  # Tenant (Public/Auth)
  registerTenant(input: RegisterTenantInput!): Tenant! @aws_api_key
  updateTenant(input: UpdateTenantInput!): Tenant! @aws_cognito_user_pools

  # Catalog (Admin)
  createCategory(input: CreateCategoryInput!): Category! @aws_cognito_user_pools
  updateCategory(input: UpdateCategoryInput!): Category! @aws_cognito_user_pools
  deleteCategory(categoryId: ID!): Category! @aws_cognito_user_pools

  createService(input: CreateServiceInput!): Service! @aws_cognito_user_pools
  updateService(input: UpdateServiceInput!): Service! @aws_cognito_user_pools
  deleteService(serviceId: ID!): Service! @aws_cognito_user_pools
  
  createProvider(input: CreateProviderInput!): Provider! @aws_cognito_user_pools
  updateProvider(input: UpdateProviderInput!): Provider! @aws_cognito_user_pools
  deleteProvider(providerId: ID!): Provider! @aws_cognito_user_pools

  createRoom(input: CreateRoomInput!): Room! @aws_cognito_user_pools
  updateRoom(input: UpdateRoomInput!): Room! @aws_cognito_user_pools
  deleteRoom(roomId: ID!): Room! @aws_cognito_user_pools
  
  # Availability (Admin)
  setProviderAvailability(input: SetAvailabilityInput!): ProviderAvailability! @aws_cognito_user_pools
  setProviderExceptions(input: SetExceptionsInput!): ProviderExceptions! @aws_cognito_user_pools
  
  # FAQs (Admin)
  createFAQ(input: CreateFAQInput!): FAQ! @aws_cognito_user_pools
  updateFAQ(input: UpdateFAQInput!): FAQ! @aws_cognito_user_pools
  deleteFAQ(faqId: ID!): FAQ! @aws_cognito_user_pools

  # Workflows (Admin)
  createWorkflow(input: CreateWorkflowInput!): Workflow! @aws_cognito_user_pools
  updateWorkflow(input: UpdateWorkflowInput!): Workflow! @aws_cognito_user_pools
  deleteWorkflow(workflowId: ID!): Workflow! @aws_cognito_user_pools

  # Documents (Knowledge Base)
  getUploadUrl(fileName: String!, contentType: String!): String! @aws_cognito_user_pools

  # Bookings
  createBooking(input: CreateBookingInput!): Booking! @aws_api_key @aws_cognito_user_pools
  confirmBooking(input: ConfirmBookingInput!): Booking! @aws_cognito_user_pools
  cancelBooking(input: CancelBookingInput!): Booking! @aws_cognito_user_pools
  markAsNoShow(bookingId: ID!): Booking! @aws_cognito_user_pools
  
  # User Management (Admin)
  inviteUser(input: InviteUserInput!): TenantUser! @aws_cognito_user_pools
  updateUserRole(input: UpdateUserRoleInput!): TenantUser! @aws_cognito_user_pools
  removeUser(userId: ID!): TenantUser! @aws_cognito_user_pools

  # Chat
  startConversation(input: StartConversationInput!): ChatResponse! @aws_api_key
  sendMessage(input: SendMessageInput!): ChatResponse! @aws_api_key
  confirmBookingFromConversation(input: ConfirmBookingFromConversationInput!): ChatResponse! @aws_api_key
}

schema {
  query: Query
  mutation: Mutation
}
`;
  }

  private createSchemaFile(schema: string): string {
    const schemaPath = path.join(__dirname, '../schema.graphql');
    fs.writeFileSync(schemaPath, schema);
    return schemaPath;
  }

  private createResolvers(
    catalogDataSource: appsync.LambdaDataSource,
    availabilityDataSource: appsync.LambdaDataSource,
    bookingDataSource: appsync.LambdaDataSource,
    chatAgentDataSource: appsync.LambdaDataSource,
    registerTenantDataSource: appsync.LambdaDataSource,
    updateTenantDataSource: appsync.LambdaDataSource,
    getTenantDataSource: appsync.LambdaDataSource,
    metricsDataSource: appsync.LambdaDataSource,
    workflowManagerDataSource: appsync.LambdaDataSource,
    faqManagerDataSource: appsync.LambdaDataSource,
    presignDataSource: appsync.LambdaDataSource
  ): void {
    const requestTemplate = appsync.MappingTemplate.fromString(`{
      "version": "2018-05-29",
      "operation": "Invoke",
      "payload": {
        "arguments": $util.toJson($context.arguments),
        "identity": $util.toJson($context.identity),
        "source": $util.toJson($context.source),
        "request": {
          "headers": $util.toJson($context.request.headers)
        },
        "info": $util.toJson($context.info)
      }
    }`);

    const responseTemplate = appsync.MappingTemplate.lambdaResult();

    // Register Tenant Resolver
    registerTenantDataSource.createResolver('RegisterTenantResolver', {
      typeName: 'Mutation',
      fieldName: 'registerTenant',
      requestMappingTemplate: requestTemplate,
      responseMappingTemplate: responseTemplate,
    });

    // Update Tenant Resolver
    updateTenantDataSource.createResolver('UpdateTenantResolver', {
      typeName: 'Mutation',
      fieldName: 'updateTenant',
      requestMappingTemplate: requestTemplate,
      responseMappingTemplate: responseTemplate,
    });

    // Get Tenant Resolver
    getTenantDataSource.createResolver('GetTenantResolver', {
      typeName: 'Query',
      fieldName: 'getTenant',
      requestMappingTemplate: requestTemplate,
      responseMappingTemplate: responseTemplate,
    });

    // Catalog resolvers
    catalogDataSource.createResolver('SearchServicesResolver', {
      typeName: 'Query',
      fieldName: 'searchServices',
      requestMappingTemplate: requestTemplate,
      responseMappingTemplate: responseTemplate,
    });

    catalogDataSource.createResolver('GetServiceResolver', {
      typeName: 'Query',
      fieldName: 'getService',
      requestMappingTemplate: requestTemplate,
      responseMappingTemplate: responseTemplate,
    });

    catalogDataSource.createResolver('ListProvidersResolver', {
      typeName: 'Query',
      fieldName: 'listProviders',
      requestMappingTemplate: requestTemplate,
      responseMappingTemplate: responseTemplate,
    });

    catalogDataSource.createResolver('ListProvidersByServiceResolver', {
      typeName: 'Query',
      fieldName: 'listProvidersByService',
      requestMappingTemplate: requestTemplate,
      responseMappingTemplate: responseTemplate,
    });

    catalogDataSource.createResolver('CreateServiceResolver', {
      typeName: 'Mutation',
      fieldName: 'createService',
      requestMappingTemplate: requestTemplate,
      responseMappingTemplate: responseTemplate,
    });

    // Room Resolvers (Catalog)
    const roomQueryFields = ['listRooms', 'getRoom'];
    roomQueryFields.forEach(field => {
      catalogDataSource.createResolver(`RoomQuery${field}Resolver`, {
        typeName: 'Query',
        fieldName: field,
        requestMappingTemplate: requestTemplate,
        responseMappingTemplate: responseTemplate,
      });
    });

    const roomMutationFields = ['createRoom', 'updateRoom', 'deleteRoom'];
    roomMutationFields.forEach(field => {
      catalogDataSource.createResolver(`RoomMutation${field}Resolver`, {
        typeName: 'Mutation',
        fieldName: field,
        requestMappingTemplate: requestTemplate,
        responseMappingTemplate: responseTemplate,
      });
    });

    catalogDataSource.createResolver('UpdateServiceResolver', {
      typeName: 'Mutation',
      fieldName: 'updateService',
      requestMappingTemplate: requestTemplate,
      responseMappingTemplate: responseTemplate,
    });

    catalogDataSource.createResolver('DeleteServiceResolver', {
      typeName: 'Mutation',
      fieldName: 'deleteService',
      requestMappingTemplate: requestTemplate,
      responseMappingTemplate: responseTemplate,
    });

    catalogDataSource.createResolver('ListCategoriesResolver', {
      typeName: 'Query',
      fieldName: 'listCategories',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    catalogDataSource.createResolver('CreateCategoryResolver', {
      typeName: 'Mutation',
      fieldName: 'createCategory',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    catalogDataSource.createResolver('UpdateCategoryResolver', {
      typeName: 'Mutation',
      fieldName: 'updateCategory',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    // Documents Resolver
    presignDataSource.createResolver('GetUploadUrlResolver', {
      typeName: 'Mutation',
      fieldName: 'getUploadUrl',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });
    catalogDataSource.createResolver('DeleteCategoryResolver', {
      typeName: 'Mutation',
      fieldName: 'deleteCategory',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    catalogDataSource.createResolver('CreateProviderResolver', {
      typeName: 'Mutation',
      fieldName: 'createProvider',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    catalogDataSource.createResolver('UpdateProviderResolver', {
      typeName: 'Mutation',
      fieldName: 'updateProvider',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    catalogDataSource.createResolver('DeleteProviderResolver', {
      typeName: 'Mutation',
      fieldName: 'deleteProvider',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    // Availability resolvers
    availabilityDataSource.createResolver('GetAvailableSlotsResolver', {
      typeName: 'Query',
      fieldName: 'getAvailableSlots',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    availabilityDataSource.createResolver('SetProviderAvailabilityResolver', {
      typeName: 'Mutation',
      fieldName: 'setProviderAvailability',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    availabilityDataSource.createResolver('GetProviderAvailabilityResolver', {
      typeName: 'Query',
      fieldName: 'getProviderAvailability',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    availabilityDataSource.createResolver('SetProviderExceptionsResolver', {
      typeName: 'Mutation',
      fieldName: 'setProviderExceptions',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    // Booking resolvers
    bookingDataSource.createResolver('GetBookingResolver', {
      typeName: 'Query',
      fieldName: 'getBooking',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    bookingDataSource.createResolver('ListBookingsByProviderResolver', {
      typeName: 'Query',
      fieldName: 'listBookingsByProvider',
      requestMappingTemplate: requestTemplate,
      responseMappingTemplate: responseTemplate,
    });

    bookingDataSource.createResolver('ListBookingsByClientResolver', {
      typeName: 'Query',
      fieldName: 'listBookingsByClient',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    bookingDataSource.createResolver('GetBookingByConversationResolver', {
      typeName: 'Query',
      fieldName: 'getBookingByConversation',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    bookingDataSource.createResolver('CreateBookingResolver', {
      typeName: 'Mutation',
      fieldName: 'createBooking',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });


    // Workflow resolvers
    workflowManagerDataSource.createResolver('ListWorkflowsResolver', {
      typeName: 'Query',
      fieldName: 'listWorkflows',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    workflowManagerDataSource.createResolver('GetWorkflowResolver', {
      typeName: 'Query',
      fieldName: 'getWorkflow',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    workflowManagerDataSource.createResolver('CreateWorkflowResolver', {
      typeName: 'Mutation',
      fieldName: 'createWorkflow',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    workflowManagerDataSource.createResolver('UpdateWorkflowResolver', {
      typeName: 'Mutation',
      fieldName: 'updateWorkflow',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    workflowManagerDataSource.createResolver('DeleteWorkflowResolver', {
      typeName: 'Mutation',
      fieldName: 'deleteWorkflow',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    // FAQ Resolvers
    faqManagerDataSource.createResolver('ListFAQsResolver', {
      typeName: 'Query',
      fieldName: 'listFAQs',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    faqManagerDataSource.createResolver('CreateFAQResolver', {
      typeName: 'Mutation',
      fieldName: 'createFAQ',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    faqManagerDataSource.createResolver('UpdateFAQResolver', {
      typeName: 'Mutation',
      fieldName: 'updateFAQ',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    faqManagerDataSource.createResolver('DeleteFAQResolver', {
      typeName: 'Mutation',
      fieldName: 'deleteFAQ',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    bookingDataSource.createResolver('ConfirmBookingResolver', {
      typeName: 'Mutation',
      fieldName: 'confirmBooking',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    bookingDataSource.createResolver('CancelBookingResolver', {
      typeName: 'Mutation',
      fieldName: 'cancelBooking',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    bookingDataSource.createResolver('MarkAsNoShowResolver', {
      typeName: 'Mutation',
      fieldName: 'markAsNoShow',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    // Chat Agent resolvers
    chatAgentDataSource.createResolver('StartConversationResolver', {
      typeName: 'Mutation',
      fieldName: 'startConversation',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    chatAgentDataSource.createResolver('SendMessageResolver', {
      typeName: 'Mutation',
      fieldName: 'sendMessage',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    chatAgentDataSource.createResolver('ConfirmBookingFromConversationResolver', {
      typeName: 'Mutation',
      fieldName: 'confirmBookingFromConversation',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    chatAgentDataSource.createResolver('GetConversationResolver', {
      typeName: 'Query',
      fieldName: 'getConversation',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    // Metrics resolvers
    metricsDataSource.createResolver('GetDashboardMetricsResolver', {
      typeName: 'Query',
      fieldName: 'getDashboardMetrics',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });

    metricsDataSource.createResolver('GetPlanUsageResolver', {
      typeName: 'Query',
      fieldName: 'getPlanUsage',
      requestMappingTemplate: appsync.MappingTemplate.lambdaRequest(),
      responseMappingTemplate: appsync.MappingTemplate.lambdaResult(),
    });
  }
}
