import * as cdk from 'aws-cdk-lib';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import { Construct } from 'constructs';

/**
 * Auth Stack
 * 
 * Creates Cognito User Pool for admin panel authentication
 * 
 * Features:
 * - Email-based sign-in
 * - Custom attribute for tenantId
 * - Admin and Staff user groups
 * - Self-service password reset
 * - MFA optional
 */
export class AuthStack extends cdk.Stack {
  public readonly userPool: cognito.UserPool;
  public readonly userPoolClient: cognito.UserPoolClient;
  public readonly adminGroup: cognito.CfnUserPoolGroup;
  public readonly staffGroup: cognito.CfnUserPoolGroup;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // Create User Pool
    this.userPool = new cognito.UserPool(this, 'AdminUserPool', {
      userPoolName: 'ChatBooking-AdminUsers',
      selfSignUpEnabled: false, // Only admins can create accounts
      signInAliases: {
        email: true,
        username: false,
      },
      autoVerify: {
        email: true,
      },
      standardAttributes: {
        email: {
          required: true,
          mutable: true,
        },
        fullname: {
          required: true,
          mutable: true,
        },
      },
      customAttributes: {
        tenantId: new cognito.StringAttribute({
          minLen: 3,
          maxLen: 50,
          mutable: false, // Cannot change tenant after creation
        }),
      },
      passwordPolicy: {
        minLength: 8,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: false,
        tempPasswordValidity: cdk.Duration.days(7),
      },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy: cdk.RemovalPolicy.RETAIN, // Don't delete user data
      mfa: cognito.Mfa.OPTIONAL,
      mfaSecondFactor: {
        sms: true,
        otp: true,
      },
      advancedSecurityMode: cognito.AdvancedSecurityMode.ENFORCED,
    });

    // Create User Pool Client for web app
    this.userPoolClient = this.userPool.addClient('AdminWebClient', {
      userPoolClientName: 'ChatBooking-AdminWeb',
      authFlows: {
        userPassword: true,
        userSrp: true,
      },
      oAuth: {
        flows: {
          authorizationCodeGrant: true,
        },
        scopes: [
          cognito.OAuthScope.EMAIL,
          cognito.OAuthScope.OPENID,
          cognito.OAuthScope.PROFILE,
        ],
        callbackUrls: [
          'http://localhost:3000/auth/callback',
          'https://admin.chatbooking.com/auth/callback',
        ],
        logoutUrls: [
          'http://localhost:3000',
          'https://admin.chatbooking.com',
        ],
      },
      generateSecret: false, // SPA doesn't use client secret
      preventUserExistenceErrors: true,
      refreshTokenValidity: cdk.Duration.days(30),
      accessTokenValidity: cdk.Duration.hours(1),
      idTokenValidity: cdk.Duration.hours(1),
    });

    // Create Admin Group
    this.adminGroup = new cognito.CfnUserPoolGroup(this, 'AdminGroup', {
      userPoolId: this.userPool.userPoolId,
      groupName: 'admin',
      description: 'Administrators with full access',
      precedence: 1,
    });

    // Create Staff Group
    this.staffGroup = new cognito.CfnUserPoolGroup(this, 'StaffGroup', {
      userPoolId: this.userPool.userPoolId,
      groupName: 'staff',
      description: 'Staff with limited access',
      precedence: 2,
    });

    // Create User Pool Domain for hosted UI
    const domain = this.userPool.addDomain('AdminDomain', {
      cognitoDomain: {
        domainPrefix: `chatbooking-admin-${this.account}`,
      },
    });

    // Outputs
    new cdk.CfnOutput(this, 'UserPoolId', {
      value: this.userPool.userPoolId,
      description: 'Cognito User Pool ID',
    });

    new cdk.CfnOutput(this, 'UserPoolArn', {
      value: this.userPool.userPoolArn,
      description: 'Cognito User Pool ARN',
    });

    new cdk.CfnOutput(this, 'UserPoolClientId', {
      value: this.userPoolClient.userPoolClientId,
      description: 'Cognito User Pool Client ID',
    });

    new cdk.CfnOutput(this, 'UserPoolDomain', {
      value: domain.domainName,
      description: 'Cognito Hosted UI Domain',
    });

    new cdk.CfnOutput(this, 'UserPoolLoginUrl', {
      value: `https://${domain.domainName}.auth.${this.region}.amazoncognito.com/login?client_id=${this.userPoolClient.userPoolClientId}&response_type=code&redirect_uri=http://localhost:3000/auth/callback`,
      description: 'Cognito Hosted UI Login URL (localhost)',
    });
  }
}
