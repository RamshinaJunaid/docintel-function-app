import azure.functions as func
import logging
import os
import json
import traceback
import urllib.parse
from azure.cosmos import CosmosClient
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential

app = func.FunctionApp()

@app.blob_trigger(arg_name="inputblob", 
                  path="raw-uploads/{name}",
                  connection="DocStorageConn")
def process_document(inputblob: func.InputStream):
    logging.info(f"Python blob trigger function processed blob \n"
                 f"Name: {inputblob.name}\n"
                 f"Size: {inputblob.length} bytes")

    file_name = os.path.basename(inputblob.name)
    extracted_content = ""

    # 1. Call Azure AI Document Intelligence
    try:
        endpoint = os.environ.get("DOCUMENT_INTELLIGENCE_ENDPOINT")
        key = os.environ.get("DOCUMENT_INTELLIGENCE_KEY")
        
        if endpoint and key:
            document_client = DocumentIntelligenceClient(endpoint=endpoint, credential=AzureKeyCredential(key))
            
            # Use prebuilt-layout or prebuilt-read model to analyze the stream
            poller = document_client.begin_analyze_document(
                model_id="prebuilt-read",
                body=inputblob.read()
            )
            result = poller.result()
            
            # Extract text content from pages
            if result.pages:
                extracted_content = " ".join([line.content for page in result.pages for line in page.lines])
            logging.info(f"Successfully extracted text from {file_name} using Document Intelligence.")
        else:
            logging.warning("Document Intelligence credentials not found in environment variables.")
    except Exception as ai_err:
        logging.error(f"Error during Document Intelligence analysis: {str(ai_err)}")

    # 2. Prepare metadata and extraction record
    document_record = {
        "id": file_name,
        "filename": file_name,
        "size_bytes": inputblob.length,
        "status": "Processed with AI",
        "extracted_text": extracted_content
    }

    # 3. Save to Cosmos DB
    try:
        connection_string = os.environ["CosmosDBConnection"]
        client = CosmosClient.from_connection_string(connection_string)
        
        database = client.get_database_client("doc-metadata-db")
        container = database.get_container_client("metadata")
        
        container.upsert_item(document_record)
        logging.info(f"Successfully saved metadata and extracted text for {file_name} to Cosmos DB!")
        
    except Exception as e:
        logging.error(f"Error saving to Cosmos DB: {str(e)}")
        logging.error(traceback.format_exc())
# -----end -----
       

@app.route(route="delete-metadata", auth_level=func.AuthLevel.FUNCTION)
def delete_document_metadata(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("HTTP trigger received an Event Grid request.")
    
    try:
        events = req.get_json()
        if not isinstance(events, list):
            events = [events]

        for event in events:
            event_type = event.get("eventType")
            
            # 1. Handle Event Grid Subscription Validation Handshake
            if event_type == "Microsoft.EventGrid.SubscriptionValidationEvent":
                validation_code = event.get("data", {}).get("validationCode")
                logging.info(f"Handling validation handshake with code: {validation_code}")
                return func.HttpResponse(
                    body=json.dumps({"validationResponse": validation_code}),
                    status_code=200,
                    mimetype="application/json"
                )
            
            # 2. Handle Blob Deleted Event
            elif event_type == "Microsoft.Storage.BlobDeleted":
                subject = event.get("subject", "")
                logging.info(f"Blob deleted event received for subject: {subject}")
                
                if "/blobs/" in subject:
                    raw_file_name = subject.split("/")[-1]
                    file_name = urllib.parse.unquote(raw_file_name)
                    
                    logging.info(f"Attempting to delete record for file: {file_name}")

                    if file_name:
                        try:
                            connection_string = os.environ["CosmosDBConnection"]
                            client = CosmosClient.from_connection_string(connection_string)
                            database = client.get_database_client("doc-metadata-db")
                            container = database.get_container_client("metadata")
                            
                            container.delete_item(item=file_name, partition_key=file_name)
                            logging.info(f"Successfully deleted metadata record for {file_name} from Cosmos DB.")
                        except Exception as e:
                            logging.error(f"Error deleting record from Cosmos DB: {str(e)}")

        return func.HttpResponse("Events processed successfully.", status_code=200)

    except Exception as e:
        logging.error(f"Error processing webhook request: {str(e)}")
        return func.HttpResponse(f"Error: {str(e)}", status_code=500)