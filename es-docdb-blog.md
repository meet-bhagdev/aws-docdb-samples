# Streaming data from Amazon DocumentDB (with MongoDB compatibility) to Amazon Elasticsearch Service using change streams

[Amazon DocumentDB (with MongoDB compatibility)](https://aws.amazon.com/documentdb/) is a fast, scalable, highly available, and fully managed document database service that supports MongoDB workloads. You can use the same MongoDB application code, drivers, and tools to run, manage, and scale workloads on Amazon DocumentDB without worrying about managing the underlying infrastructure. As a document database, Amazon DocumentDB makes it easy to store, query, and index JSON data.


As use-cases evolve, customers want to be able gain further insights from their data. For example, let’s consider a social media platform that uses Amazon DocumentDB to store their user profiles and user content data modeled as JSON documents. As the platform grows and use cases evolve, they want to be able to search the user content to find patterns related to specific words. For example, they may want to determine which users post about sports, determine which users share content about dogs or search data for specific tags. This can be done easily by running a full text query on the data. Amazon Elasticsearch Service is purpose-built to enable customers to run full text search queries over their data. 


In this post we will show you how to integrate Amazon DocumentDB with Amazon Elasticsearch service, to enable you to run full text search queries over your Amazon DocumentDB data. Specifically, we will show you how to use an AWS Lambda function to stream events from your Amazon DocumentDB cluster’s change stream to an Amazon Elasticsearch Service domain, to enable the ability to run full text search queries on the data. To automate the solution, we will use Amazon EventBridge to trigger a message every 120 seconds to Amazon Simple Notification Service (SNS), which will in turn invoke the Lambda function on a schedule. 

The following diagram shows the final architecture of this walkthrough.
[Image: images/image.png]

### Walkthrough overview

This post includes the following tasks in the walk through:

1. Deploy an [AWS CloudFormation](http://aws.amazon.com/cloudformation) template to launch an Amazon DocumentDB cluster, Amazon Elasticsearch Service domain, AWS Cloud9 environment, AWS Secrets Manager secret to manage Amazon DocumentDB credentials, Amazon Simple Notification Service (SNS) trigger and an Amazon EventBridge rule
2. Setup an AWS Cloud9 environment
3. Enable change streams on Amazon DocumentDB
4. Setup and deploy the AWS Lambda streaming function that replicates change events from an Amazon DocumentDB cluster to Amazon Elastic Search Service domain
    
5. Execute full text search queries


### Step 1. Deploy AWS CloudFormation template


AWS CloudFormation provides a common language for you to model and provision AWS resources in your cloud environment. For this walkthrough, you will deploy an AWS CloudFormation template that will create - 

* Amazon DocumentDB cluster: operational data store for JSON data
* Amazon Elasticsearch Service domain: To execute full text search queries
* AWS Cloud9 environment: integrated development environment (IDE)
* AWS Secrets Manager secret: manage Amazon DocumentDB credentials,
* Amazon Simple Notification Service (SNS) trigger and Amazon EventBridge rule: automate the solution and run the AWS Lambda function every 120 seconds 


To deploy the template:

1. Go to AWS CloudFormation in AWS console and select **Create stack**. 
2. Check the **Upload a template file** option, select **Choose file **option and upload the [change stream stack](https://raw.githubusercontent.com/aws-samples/amazon-documentdb-samples/master/samples/change-streams/setup/docdb_change_streams.yml)yaml file, and select **Next.**
3. Give your stack a name, and input username, password, the identifier for your Amazon DocumentDB cluster, select **Next**. 
4. AWS Cloud9 uses a Role and an Instance profile. If you have used Cloud9 before, those have been created automatically for you; therefore, select **true** in the options for **ExistingCloud9Role** and **ExistingCloud9InstanceProfile**. Otherwise, leave it as **false**. 
5. Leave everything as default and select **Next**. Check the box to allow the stack create a role on behalf of you and select **Create stack**. The stack should complete provisioning in a few minutes. 


![Alt Text](/images/cfn.gif)


### Step 2. Setup an AWS Cloud9 environment

AWS Cloud9 is a cloud-based integrated development environment (IDE). From the AWS Management Console, select AWS Cloud9 and launch the environment that was created with the AWS CloudFormation stack. 

* From your AWS Cloud9 environment, launch a new tab to open the Preferences tab
* Select **AWS SETTINGS **from the left navigation pane
* Turn off **AWS managed temporary credentials. **This enables us to simplify the developer experience later in the walkthrough
* Close the Preferences tab 

![Alt Text](/images/cloud9Credentials.gif)

From the terminal in your Cloud9 environment, remove any existing credentials file:

```
`rm -vf ${HOME}/.aws/credentials`
```


Create an environment variable for the AWS CloudFormation stack name you created using the commands below. We will use this environment variable later in the walk through. 

```
`export`` STACK``=<``Name`` ``of`` your ``CloudFormation`` stack``>
#This should match the AWS CloudFormation stack name you specified in the previous step`
```


Configure AWS CLI to use the current region as the default

```
`export AWS_REGION=$(curl -s 169.254.169.254/latest/dynamic/instance-identity/document | grep region | cut -d\" -f4)`
```


Download and execute startup.sh file by executing the commands below. This startup script will update and install the required python libraries, package the code for your AWS Lambda function, upload it to an Amazon S3 bucket, and copy the output of the AWS CloudFormation stack to the AWS Cloud9 environment. 

```
curl -s https://raw.githubusercontent.com/aws-samples/amazon-documentdb-samples/master/samples/change-streams/setup/startup.sh -o startup.sh
`chmod ``700`` startup``.``sh`
`./``startup``.``sh`
```



### Step 3. **Enable change streams on Amazon DocumentDB**

[Amazon DocumentDB change streams](https://docs.aws.amazon.com/documentdb/latest/developerguide/change_streams.html#change_streams-enabling) provide a time ordered sequence of update events that occur within your cluster’s collections and databases. You can poll change streams on individual collections, and read change events (INSERTS, UPDATES and DELETES) as they occur. We will use change streams to stream change events from your Amazon DocumentDB cluster to an Amazon Elasticsearch service index. To enable change streams on the cluster, execute the commands below (replace with the values of your cluster). First, we will use the mongo shell to log into the database:


```
`export`` USERNAME``=<``DocumentDB`` cluster username``>`
`echo ``"export USERNAME=${USERNAME}"`` ``>>`` ``~/.``bash_profile`

`export`` PASSWORD``=<``DocumentDB`` cluster password``>`
`echo ``"export PASSWORD=${PASSWORD}"`` ``>>`` ``~/.``bash_profile`

export DOCDB_ENDPOINT=$(jq < cfn-output.json -r '.DocumentDBEndpoint')
`echo ``"export DOCDB_ENDPOINT=${DOCDB_ENDPOINT}"`` ``>>`` ``~/.``bash_profile`

#Log in to your Amazon DocumentDB cluster
`mongo ``--``ssl ``--``host ``$DOCDB_ENDPOINT``:``27017`` ``--``sslCAFile rds``-``combined``-``ca``-``bundle``.``pem ``--``username $USERNAME ``--``password $PASSWORD`
```

Next, enable the change stream on your cluster using the command below:

```
`db.adminCommand({modifyChangeStreams: 1, database: "", collection: "", enable: true});`
```

You should get this response:

```
`{ "ok" : 1 }`
```



### **Step 4. Setup and deploy the AWS Lambda ****function**

The AWS Lambda function will retrieve Amazon DocumentDB credentials from AWS Secrets Manager, setup a connection to the Amazon DocumentDB cluster, read the change events from the Amazon DocumentDB change stream and replicate them to an Amazon Elasticsearch service index. The function will also store a change stream resume token in the Amazon DocumentDB cluster so it knows where to resume on its next run. To automate the solution, we will poll for changes every 120 seconds. We will use Amazon EventBridge to trigger a message to Amazon Simple Notification Service (SNS), which will in turn invoke the function.

The Lambda function uses three variables that you can tune:

* Lambda timeout: Duration after which the Lambda function times out. The default is set to 120 seconds
    
* MAX_LOOP: Variable that controls how many documents to scan from the changestream with every Lambda run. The default is set to 1000. 
* STATE_SYNC_COUNT: Variable that determines how many iterations the AWS Lambda function will wait before syncing the resume token (resume token to track the events processed in the Change Stream). The default is set to 15.


To deploy the AWS Lambda function, open a new terminal in the AWS Cloud9 environment and execute the commands below. This will create and deploy a new AWS CloudFormation stack. This stack will provision the AWS Lambda function that will stream change events from your Amazon DocumentDB cluster to an Amazon Ealsticsearch service domain. The stack will be populated with environment variables for Amazon DocumentDB cluster, Amazon Elasticsearch service domain, watched database and collection name (this is the database and collection that the AWS Lambda will watch for change events), state database and collection name (this is the database and collection that be used to store last processed change event), SNS topics ARN, Lambda role ARN, and the Secrets Manager ARN. 

```
curl -s https://raw.githubusercontent.com/aws-samples/amazon-documentdb-samples/master/samples/change-streams/setup/lambda_function_config.sh -o lambda_function_config.sh
`chmod ``700`` lambda_function_config``.``sh`
`./``lambda_function_config``.``sh`
```



### Step 5: Execute full text search queries

From your AWS Cloud9 terminal, execute the following command to insert sample data into your Amazon DocumentDB cluster. For the purposes of this walkthrough, we are inserting a few tweets from new year’s eve in 2014. 

```
#Execute Python script to inserext data into your Amazon DocumentDB cluster
`python es``-``test``.``py`
```

Validate that documents were inserted by authenticating into your Amazon DocumentDB cluster from the mongo shell and using the following command:

```
`mongo --ssl --host $DOCDB_ENDPOINT:27017 --sslCAFile rds-combined-ca-bundle.pem --username $USERNAME --password $PASSWORD
use`` sampledb`
`db``.``tweets``.``find``()`
```

Once the data is inserted into your Amazon DocumentDB cluster, it will autoamatically be replicated to your Amazon Elasticsearch service domain once the AWS Lambda function is executed. The default trigger value will execute your AWS Lambda function every 120 seconds. This is setup using  Amazon Event Bridge and Amazon Simple Notification Service. Alternatively, you can run the AWS Lambda function via the AWS console or the AWS CLI, for ad-hoc testing. Once the AWS Lambda function is triggered, you can then validate the data has been replicated by running the following command against your Amazon Elasticsearch Service domain from the terminal in your Cloud9 environment:

```
curl https://$(jq < cfn-output.json -r '.ElasticsearchDomainEndpoint')/_cat/indices?v
```

You should see that a new index was populated with the data from your Amazon DocumentDB cluster: 
[Image: image.png]
Once the data is replicated to your Amazon Elasticsearch Service domain, you can run full text search queries on your JSON data in the Amazon Elasticsearch domain. For example, we can execute a query to find all tweets that have some mention of “gym” in its text: 

```
curl -X GET "https://$(jq < cfn-output.json -r '.ElasticsearchDomainEndpoint')/sampledb-tweets/_search?pretty" -H 'Content-Type: application/json' -d'
{
    "query": {
        "match" : {
          "text": "gym"
        }
    }
}'
```

Expected output:
[Image: image.png]With Amazon Elasticsearch service, you can also execute fuzzy full text search queries. Fuzzy queries will returns documents that contain terms similar to the search term. For example if the search term is “hello”, documents with data matching “hellp”, “hallo”, “heloo” and more will also be matched. For example, we can execute a query to find all tweets with text that has a fuzzy match for “New”

```
 curl -X GET "https://$(jq < cfn-output.json -r '.ElasticsearchDomainEndpoint')/media-movie/_search?pretty" -H 'Content-Type: application/json' -d'
{
  "query": {
    "fuzzy": {
      "text": {
        "value": "New"
      }
    }
  }
}'
```

Expected output:
[Image: image.png]For more details on types of Amazon Elasticsearch queries, refer to [Searching data in Amazon Elasticsearch service](https://docs.aws.amazon.com/elasticsearch-service/latest/developerguide/es-searching.html)

### Clean up resources

In order to clean up the resources created in this blog post, navigate to the AWS Console and go to AWS CloudFormation. Find the stacks you created for the walkthrough, and delete them one by one. This should delete all resources associated with this walkthrough.

## Summary

This post showed you how to integrate Amazon Elasticsearch service with Amazon DocumentDB to perform full text search queries over JSON data. Specifically we used an AWS Lambda function to replicate change events from an Amazon DocumentDB change stream to an Amazon Elasticsearch service index. Change events can also be used to help integrate Amazon DocumentDB with other AWS services. For example you can replicate change stream events to Amazon Managed Streaming for Apache Kafka (or any other Apache Kafka distro), AWS Kinesis Streams, AWS SQS, and Amazon S3.

If you have any questions or comments about this blog post, please use the comments section on this page. If you are interested in looking at the source code for AWS Lambda function, have a suggestion or would like to file a bug, you can do so on our [Amazon DocumentDB samples Github repository](https://github.com/aws-samples/amazon-documentdb-samples/blob/master/samples/change-streams/app/lambda_function.py). If you have any features requests for Amazon DocumentDB, email us at [documentdb-feature-request@amazon.com](mailto:documentdb-feature-request@amazon.com).
