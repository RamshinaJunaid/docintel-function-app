import azure.functions as func
import logging
import os
import json
import traceback
import urllib.parse
import hashlib
import mimetypes
from azure.cosmos import CosmosClient
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobServiceClient

app = func.FunctionApp()

# ==========================================
# 1. Blob Trigger: Ingestion, Hashing, & Archival
# ==========================================
@app.blob_trigger(arg_name="inputblob", 
                  path="raw-uploads/{name}",
                  connection="DocStorageConn")
def process_document(inputblob: func.InputStream):
    file_name = os.path.basename(inputblob.name)
    logging.info(f"Processing started for: {file_name}")

    # Read blob stream into memory once for all operations
    blob_bytes = inputblob.read()
    
    # 1. Extended Metadata Extraction (SHA-256 & MIME Type)
    sha256_hash = hashlib.sha256(blob_bytes).hexdigest()
    mime_type, _ = mimetypes.guess_type(file_name)
    mime_type = mime_type or 'application/octet-stream'

    extracted_content = ""

    # 2. Call Azure AI Document Intelligence
    try:
        endpoint = os.environ.get("DOCUMENT_INTELLIGENCE_ENDPOINT")
        key = os.environ.get("DOCUMENT_INTELLIGENCE_KEY")
        
        if endpoint and key:
            document_client = DocumentIntelligenceClient(endpoint=endpoint, credential=AzureKeyCredential(key))
            
            poller = document_client.begin_analyze_document(
                model_id="prebuilt-read",
                body=blob_bytes  # Use the in-memory bytes
            )
            result = poller.result()
            
            if result.pages:
                extracted_content = " ".join([line.content for page in result.pages for line in page.lines])
            logging.info(f"Successfully extracted text from {file_name}")
        else:
            logging.warning("Document Intelligence credentials not found.")
    except Exception as ai_err:
        logging.error(f"Error during Document Intelligence analysis: {str(ai_err)}")

    # 3. Prepare enterprise metadata payload
    document_record = {
        "id": file_name,
        "filename": file_name,
        "size_bytes": inputblob.length,
        "mime_type": mime_type,
        "sha256_hash": sha256_hash,
        "status": "Processed and Archived",
        "extracted_text": extracted_content
    }

    # 4. Save to Cosmos DB
    try:
        connection_string = os.environ["CosmosDBConnection"]
        client = CosmosClient.from_connection_string(connection_string)
        
        database = client.get_database_client("doc-metadata-db")
        container = database.get_container_client("metadata")
        
        container.upsert_item(document_record)
        logging.info(f"Saved extended metadata for {file_name} to Cosmos DB.")
        
    except Exception as e:
        logging.error(f"Error saving to Cosmos DB: {str(e)}")
        logging.error(traceback.format_exc())

    # 5. Archival Flow: Move document to 'processed-docs'
    try:
        storage_conn = os.environ["DocStorageConn"]
        blob_service_client = BlobServiceClient.from_connection_string(storage_conn)
        
        # Upload to processed container
        processed_blob = blob_service_client.get_blob_client(container="processed-docs", blob=file_name)
        processed_blob.upload_blob(blob_bytes, overwrite=True)
        
        # Delete from raw container
        raw_blob = blob_service_client.get_blob_client(container="raw-uploads", blob=file_name)
        raw_blob.delete_blob()
        
        logging.info(f"Successfully archived {file_name} to 'processed-docs'.")
    except Exception as e:
        logging.error(f"Error during archival routing for {file_name}: {str(e)}")


# ==========================================
# 2. Native Event Grid Trigger: Synchronized Deletion
# ==========================================
@app.event_grid_trigger(arg_name="event")
def delete_document_metadata(event: func.EventGridEvent):
    if event.event_type == "Microsoft.Storage.BlobDeleted":
        subject = event.subject
        
        # CRITICAL: Only delete DB metadata if the blob was deleted from the final archive (processed-docs)
        # This prevents premature deletion when the file is moved out of 'raw-uploads'
        if "/containers/processed-docs/blobs/" in subject:
            raw_file_name = subject.split("/")[-1]
            file_name = urllib.parse.unquote(raw_file_name)
            
            logging.info(f"Archive deletion detected. Removing Cosmos DB record for: {file_name}")

            if file_name:
                try:
                    connection_string = os.environ["CosmosDBConnection"]
                    client = CosmosClient.from_connection_string(connection_string)
                    database = client.get_database_client("doc-metadata-db")
                    container = database.get_container_client("metadata")

                    container.delete_item(item=file_name, partition_key=file_name)
                    logging.info(f"Successfully purged metadata for {file_name}.")
                except Exception as e:
                    logging.error(f"Error deleting record from Cosmos DB: {str(e)}")