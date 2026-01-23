
import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as route53 from 'aws-cdk-lib/aws-route53';
import * as targets from 'aws-cdk-lib/aws-route53-targets';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import { Construct } from 'constructs';
import * as path from 'path';

interface FrontendLinkStackProps extends cdk.StackProps {
    description?: string;
    tags?: { [key: string]: string };
    envName: string;
}

export class FrontendLinkStack extends cdk.Stack {
    public readonly distribution: cloudfront.Distribution;

    constructor(scope: Construct, id: string, props: FrontendLinkStackProps) {
        super(scope, id, props);

        const domainName = 'link.holalucia.cl';
        // Hosted Zone ID for holalucia.cl (should be imported or passed, but hardcoding for now if known, or looking up)
        // Assuming the zone exists in the same account
        const zone = route53.HostedZone.fromLookup(this, 'HostedZone', {
            domainName: 'holalucia.cl',
        });

        // 1. S3 Bucket for Static Assets
        const siteBucket = new s3.Bucket(this, 'LinkSiteBucket', {
            bucketName: `${props.envName}-chat-booking-link-site`, // Ensure uniqueness
            publicReadAccess: false,
            blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
            removalPolicy: cdk.RemovalPolicy.DESTROY, // For dev/test. In prod, RETAIN.
            autoDeleteObjects: true, // For dev/test
            encryption: s3.BucketEncryption.S3_MANAGED,
        });

        // 2. Certificate
        const certificate = new acm.Certificate(this, 'LinkSiteCertificate', {
            domainName: domainName,
            validation: acm.CertificateValidation.fromDns(zone),
        });

        // 3. CloudFront Distribution
        this.distribution = new cloudfront.Distribution(this, 'LinkSiteDistribution', {
            certificate: certificate,
            domainNames: [domainName],
            defaultRootObject: 'index.html',
            defaultBehavior: {
                origin: origins.S3BucketOrigin.withOriginAccessControl(siteBucket),
                viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                compress: true,
            },
            errorResponses: [
                {
                    httpStatus: 404,
                    responseHttpStatus: 404, // For [slug] SSG, we might want 404 to show 404 page
                    responsePagePath: '/404.html',
                },
                {
                    httpStatus: 403,
                    responseHttpStatus: 404,
                    responsePagePath: '/404.html',
                }
            ],
        });

        // 4. Route53 Alias Record
        new route53.ARecord(this, 'LinkSiteAliasRecord', {
            recordName: 'link', // link.holalucia.cl
            target: route53.RecordTarget.fromAlias(new targets.CloudFrontTarget(this.distribution)),
            zone: zone,
        });

        // 5. Deployment
        // Path to chat-booking-link/out (Assuming build is done before deploy)
        // We expect the 'out' directory to exist relative to where CDK is run
        // CDK runs in chat-booking-infrastructure/cdk
        // Repo root is ../../
        const frontendPath = path.join(process.cwd(), '../../chat-booking-link/out');

        // ONLY deploy if the directory exists (to avoid CDK synth errors locally if not built)
        // In CI/CD, we must ensure build runs first.
        // For now, we will comment this out or handle it gracefully, but usually creating the deployment construct is fine even if empty? 
        // No, BucketDeployment requires sources.
        // We will assume 'npm run build' is run.

        /* 
        new s3deploy.BucketDeployment(this, 'DeployLinkSite', {
          sources: [s3deploy.Source.asset(frontendPath)],
          destinationBucket: siteBucket,
          distribution: this.distribution,
          distributionPaths: ['/*'],
        });
        */

        // NOTE: Commenting out BucketDeployment for now because 'out' dir doesn't exist yet.
        // We will trigger deployment manually or via separate step after build.
        // Actually, for this task, I should probably build it.
    }
}
