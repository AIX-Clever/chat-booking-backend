import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import { Construct } from 'constructs';

interface AssetsStackProps extends cdk.StackProps {
    stage: string;
}

export class AssetsStack extends cdk.Stack {
    public readonly assetsBucket: s3.Bucket;
    public readonly distribution: cloudfront.Distribution;

    constructor(scope: Construct, id: string, props: AssetsStackProps) {
        super(scope, id, props);

        // 1. Assets Bucket (Private)
        this.assetsBucket = new s3.Bucket(this, 'AssetsBucket', {
            bucketName: `chat-booking-assets-${props.stage}-${cdk.Aws.ACCOUNT_ID}`, // Unique name
            blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
            encryption: s3.BucketEncryption.S3_MANAGED,
            removalPolicy: props.stage === 'prod' ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
            autoDeleteObjects: props.stage !== 'prod',
            cors: [{
                allowedMethods: [s3.HttpMethods.PUT, s3.HttpMethods.POST, s3.HttpMethods.GET, s3.HttpMethods.HEAD],
                allowedOrigins: ['*'], // Restrict this in production to admin domain
                allowedHeaders: ['*'],
                exposedHeaders: ['ETag', 'x-amz-server-side-encryption', 'x-amz-request-id', 'x-amz-id-2'],
                maxAge: 3000,
            }]
        });

        // 2. CloudFront Origin Access Control (OAC)
        const cfnOriginAccessControl = new cloudfront.CfnOriginAccessControl(this, 'AssetsOAC', {
            originAccessControlConfig: {
                name: `AssetsOAC-${props.stage}`,
                originAccessControlOriginType: 's3',
                signingBehavior: 'always',
                signingProtocol: 'sigv4',
            },
        });

        // 3. CloudFront Distribution
        this.distribution = new cloudfront.Distribution(this, 'AssetsDistribution', {
            defaultBehavior: {
                origin: new origins.S3Origin(this.assetsBucket),
                viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
                allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                compress: true,
            },
            comment: `Assets for Chat Booking (${props.stage})`,
            enableLogging: true,
            enableIpv6: true,
            httpVersion: cloudfront.HttpVersion.HTTP2_AND_3,
        });

        // Attach OAC to the standard Distribution construct
        const cfnDistribution = this.distribution.node.defaultChild as cloudfront.CfnDistribution;
        cfnDistribution.addPropertyOverride('DistributionConfig.Origins.0.OriginAccessControlId', cfnOriginAccessControl.attrId);

        // Grant read permissions to CloudFront (S3 Bucket Policy)
        this.assetsBucket.addToResourcePolicy(new cdk.aws_iam.PolicyStatement({
            actions: ['s3:GetObject'],
            resources: [this.assetsBucket.arnForObjects('*')],
            principals: [new cdk.aws_iam.ServicePrincipal('cloudfront.amazonaws.com')],
            conditions: {
                StringEquals: {
                    'AWS:SourceArn': `arn:aws:cloudfront::${cdk.Aws.ACCOUNT_ID}:distribution/${this.distribution.distributionId}`
                }
            }
        }));

        // Outputs
        new cdk.CfnOutput(this, 'AssetsBucketName', {
            value: this.assetsBucket.bucketName,
        });
        new cdk.CfnOutput(this, 'AssetsDistributionDomain', {
            value: this.distribution.distributionDomainName,
        });
    }
}
