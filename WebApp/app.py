from fastapi import FastAPI, File, UploadFile, HTTPException
from azure.storage.blob import BlobServiceClient
import os
import uvicorn

app = FastAPI(title="Zero-Trust Document Ingress API")

@app.post("/upload/")
async def upload_document(file: UploadFile = File(...)):
    try:
        # Fetch the secure connection string injected by Azure App Service
        conn_str = os.environ.get("DocStorageConn")
        if not conn_str:
            raise HTTPException(status_code=500, detail="Storage connection string missing.")
        
        # Connect to the VNet-secured Blob Storage
        blob_service_client = BlobServiceClient.from_connection_string(conn_str)
        blob_client = blob_service_client.get_blob_client(container="raw-uploads", blob=file.filename)
        
        # Stream file directly into Azure Storage
        contents = await file.read()
        blob_client.upload_blob(contents, overwrite=True)
        
        return {
            "filename": file.filename, 
            "status": "Securely uploaded to raw-uploads landing zone."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)