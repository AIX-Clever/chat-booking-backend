import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';

export class VectorDatabaseStack extends cdk.Stack {
    public readonly vpc: ec2.Vpc;
    public readonly cluster: rds.DatabaseCluster;
    public readonly dbSecret: secretsmanager.ISecret;
    public readonly dbSecurityGroup: ec2.SecurityGroup;

    constructor(scope: Construct, id: string, props?: cdk.StackProps) {
        super(scope, id, props);

        // 1. VPC: Private Isolated (No Internet Access)
        this.vpc = new ec2.Vpc(this, 'ChatBookingVpc', {
            ipAddresses: ec2.IpAddresses.cidr('10.0.0.0/16'),
            availabilityZones: ['us-east-1a', 'us-east-1b'],
            subnetConfiguration: [
                {
                    cidrMask: 24,
                    name: 'Isolated',
                    subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
                },
            ],
            // No NAT Gateways = Zero Network Cost, but requires Endpoints for AWS Services
            natGateways: 0,
        });

        // 2. Security Groups
        this.dbSecurityGroup = new ec2.SecurityGroup(this, 'DbSecurityGroup', {
            vpc: this.vpc,
            description: 'Security Group for Aurora Vector DB',
            allowAllOutbound: true, // Allow DB to reach endpoints if needed
        });

        // 3. VPC Endpoints (The "Tunnels" to AWS Services)

        // Gateway Endpoints (Free, routing based)
        this.vpc.addGatewayEndpoint('DynamoDbEndpoint', {
            service: ec2.GatewayVpcEndpointAwsService.DYNAMODB,
        });

        this.vpc.addGatewayEndpoint('S3Endpoint', {
            service: ec2.GatewayVpcEndpointAwsService.S3,
        });

        // Interface Endpoints (PrivateLink, ENI based)
        // Secrets Manager (to retrieve DB credentials)
        this.vpc.addInterfaceEndpoint('SecretsManagerEndpoint', {
            service: ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
        });

        // CloudWatch Logs (to ship Lambda logs)
        this.vpc.addInterfaceEndpoint('LogsEndpoint', {
            service: ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
        });

        // Bedrock Runtime (to invoke AI models)
        this.vpc.addInterfaceEndpoint('BedrockRuntimeEndpoint', {
            service: ec2.InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME,
        });

        // 4. Aurora Serverless v2
        this.cluster = new rds.DatabaseCluster(this, 'VectorDatabase', {
            engine: rds.DatabaseClusterEngine.auroraPostgres({
                version: rds.AuroraPostgresEngineVersion.VER_15_10, // Supports pgvector 0.5.0+
            }),
            serverlessV2MinCapacity: 0.5, // Min cost
            serverlessV2MaxCapacity: 2.0, // Max scale
            writer: rds.ClusterInstance.serverlessV2('Writer', {
                publiclyAccessible: false,
            }),
            vpc: this.vpc,
            securityGroups: [this.dbSecurityGroup],
            vpcSubnets: {
                subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
            },
            defaultDatabaseName: 'chatbookingvec',
            storageEncrypted: true,
            removalPolicy: cdk.RemovalPolicy.RETAIN, // Safer for DBs
        });

        this.dbSecret = this.cluster.secret!;

        // 5. Outputs for Lambda Stack
        new cdk.CfnOutput(this, 'DatabaseEndpoint', {
            value: this.cluster.clusterEndpoint.hostname,
            description: 'Aurora Cluster Endpoint',
            exportName: 'ChatBookingVideoDbEndpoint',
        });

        new cdk.CfnOutput(this, 'DatabaseSecretArn', {
            value: this.dbSecret.secretArn,
            description: 'Aurora Secret ARN',
            exportName: 'ChatBookingVectorDbSecretArn',
        });
    }
}
