import azure.functions as func
import logging
import os
import json
import traceback
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