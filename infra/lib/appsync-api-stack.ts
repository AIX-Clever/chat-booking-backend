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
  userManagementFunction: lambda.IFunction;
  presignFunction: lambda.IFunction;
  userPool: cdk.aws_cognito.IUserPool;
}

export class AppSyncApiStack extends cdk.Stack {
  public readonly api: appsync.GraphqlApi;
  public readonly apiKey: string;

  constructor(scope: Construct, id: string, props: AppSyncApiStackProps) {
    super(scope, id, props);

    // Create AppSync API
    this.api = new appsync.GraphqlApi(this, 'ChatBookingApi', {
      name: 'ChatBookingGraphQLApi',
      schema: appsync.SchemaFile.fromAsset(path.join(process.cwd(), 'schema.graphql')),
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
      presignDataSource,
      userManagementDataSource
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
    presignDataSource: appsync.LambdaDataSource,
    userManagementDataSource: appsync.LambdaDataSource
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

    // User Management Resolvers
    userManagementDataSource.createResolver('ListTenantUsersResolver', {
      typeName: 'Query',
      fieldName: 'listTenantUsers',
      requestMappingTemplate: requestTemplate,
      responseMappingTemplate: responseTemplate,
    });

    userManagementDataSource.createResolver('GetTenantUserResolver', {
      typeName: 'Query',
      fieldName: 'getTenantUser',
      requestMappingTemplate: requestTemplate,
      responseMappingTemplate: responseTemplate,
    });

    userManagementDataSource.createResolver('InviteUserResolver', {
      typeName: 'Mutation',
      fieldName: 'inviteUser',
      requestMappingTemplate: requestTemplate,
      responseMappingTemplate: responseTemplate,
    });

    userManagementDataSource.createResolver('UpdateUserRoleResolver', {
      typeName: 'Mutation',
      fieldName: 'updateUserRole',
      requestMappingTemplate: requestTemplate,
      responseMappingTemplate: responseTemplate,
    });

    userManagementDataSource.createResolver('RemoveUserResolver', {
      typeName: 'Mutation',
      fieldName: 'removeUser',
      requestMappingTemplate: requestTemplate,
      responseMappingTemplate: responseTemplate,
    });

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

    presignDataSource.createResolver('GeneratePresignedUrlResolver', {
      typeName: 'Mutation',
      fieldName: 'generatePresignedUrl',
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
      requestMappingTemplate: requestTemplate,
      responseMappingTemplate: responseTemplate,
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
