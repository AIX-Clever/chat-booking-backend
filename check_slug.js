// Quick script to check tenant slug in DynamoDB
// Run with: node check_slug.js

const { DynamoDBClient, GetItemCommand, QueryCommand } = require("@aws-sdk/client-dynamodb");
const { unmarshall } = require("@aws-sdk/util-dynamodb");

const client = new DynamoDBClient({ region: "us-east-1" });

async function checkTenant() {
    console.log("🔍 Checking tenant data in DynamoDB...\n");

    // Get tenant by ID (you'll need to provide your tenantId)
    const tenantId = "YOUR_TENANT_ID_HERE"; // Replace with actual tenant ID

    try {
        // 1. Check direct get
        const getParams = {
            TableName: "ChatBooking-Tenants",
            Key: {
                tenantId: { S: tenantId }
            }
        };

        const result = await client.send(new GetItemCommand(getParams));

        if (result.Item) {
            const tenant = unmarshall(result.Item);
            console.log("✅ Tenant found by ID:");
            console.log("  - tenantId:", tenant.tenantId);
            console.log("  - name:", tenant.name);
            console.log("  - slug:", tenant.slug || "(empty)");
            console.log("\n");

            // 2. Try query by slug
            if (tenant.slug) {
                console.log(`🔎 Querying GSI for slug: "${tenant.slug}"`);
                const queryParams = {
                    TableName: "ChatBooking-Tenants",
                    IndexName: "slug-index",
                    KeyConditionExpression: "slug = :slug",
                    ExpressionAttributeValues: {
                        ":slug": { S: tenant.slug }
                    }
                };

                const queryResult = await client.send(new QueryCommand(queryParams));
                console.log("  GSI Query Result Count:", queryResult.Items?.length || 0);

                if (queryResult.Items && queryResult.Items.length > 0) {
                    console.log("  ✅ Tenant found via GSI");
                } else {
                    console.log("  ⚠️ Tenant NOT found via GSI (index may be propagating)");
                }
            }
        } else {
            console.log("❌ Tenant not found");
        }

    } catch (error) {
        console.error("Error:", error.message);
    }
}

checkTenant();
