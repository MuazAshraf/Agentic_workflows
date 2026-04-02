import time
from pydantic import BaseModel, Field
from llama_cloud import LlamaCloud

# Define schema using Pydantic
class Resume(BaseModel):
    name: str = Field(description="Full name of candidate")
    email: str = Field(description="Email address")
    skills: list[str] = Field(description="Technical skills and technologies")

client = LlamaCloud(api_key="your_api_key")

# Upload a file to extract from
file_obj = client.files.create(file="resume.pdf", purpose="extract")

# Extract data from document
job = client.extract.create(
    file_input=file_obj.id,
    configuration={
        "data_schema": Resume.model_json_schema(),
        "extraction_target": "per_doc",
        "tier": "agentic",
    },
)

# Poll for completion
while job.status not in ("COMPLETED", "FAILED", "CANCELLED"):
    time.sleep(2)
    job = client.extract.get(job.id)

print(job.extract_result)

Defining Schemas
Schemas can be defined using either Pydantic/Zod models or JSON Schema. Refer to the Schemas page for more details.

Other Extraction APIs
Extraction over bytes or text
You can also call extraction directly over raw text.

import io
import time
from llama_cloud import LlamaCloud

client = LlamaCloud(api_key="your_api_key")

source_text = "Candidate Name: Jane Doe\nEmail: jane.doe@example.com"
source_buffer = io.BytesIO(source_text.encode('utf-8'))

file_obj = client.files.create(file=source_buffer, purpose="extract", external_file_id="resume.txt")

job = client.extract.create(
    file_input=file_obj.id,
    configuration={
        "data_schema": Resume.model_json_schema(),
        "extraction_target": "per_doc",
        "tier": "agentic",
    },
)

while job.status not in ("COMPLETED", "FAILED", "CANCELLED"):
    time.sleep(2)
    job = client.extract.get(job.id)


    Extraction from a Parse Job ID
If you’ve already parsed a document with LlamaParse, you can pass the parse job ID directly to extraction instead of uploading the file again. This skips re-parsing, saving both time and credits. It’s especially useful when you want to extract with multiple schemas from the same document.

import time
from llama_cloud import LlamaCloud

client = LlamaCloud(api_key="your_api_key")

# Step 1: Parse the document once
parse_job = client.parsing.create(
    tier="agentic",
    version="latest",
    upload_file="./document.pdf",
)
parse_result = client.parsing.wait_for_completion(parse_job.id, verbose=True)

# Step 2: Extract using the parse job ID (no re-upload needed)
job = client.extract.create(
    file_input=parse_job.id,  # e.g. "pjb-xxxxxxxx-..."
    configuration={
        "data_schema": Resume.model_json_schema(),
        "extraction_target": "per_doc",
        "tier": "agentic",
    },
)

# Poll for completion
while job.status not in ("COMPLETED", "FAILED", "CANCELLED"):
    time.sleep(2)
    job = client.extract.get(job.id)

print(job.extract_result)

Batch Processing
Process multiple files asynchronously:

import asyncio
from llama_cloud import AsyncLlamaCloud

client = AsyncLlamaCloud(api_key="your_api_key")
semaphore = asyncio.Semaphore(5)  # Limit concurrency

EXTRACT_CONFIG = {
    "data_schema": Resume.model_json_schema(),
    "extraction_target": "per_doc",
    "tier": "agentic",
}

async def process_path(file_path: str):
    async with semaphore:
        file_obj = await client.files.create(file=file_path, purpose="extract")

        job = await client.extract.create(
            file_input=file_obj.id,
            configuration=EXTRACT_CONFIG,
        )

        while job.status not in ("COMPLETED", "FAILED", "CANCELLED"):
            await asyncio.sleep(2)
            job = await client.extract.get(job.id)

    return job.extract_result

async def main():
    file_paths = ["resume1.pdf", "resume2.pdf", "resume3.pdf"]
    results = await asyncio.gather(*(process_path(path) for path in file_paths))
    return results

asyncio.run(main())

Schema Generation
You can use the SDK to auto-generate a JSON schema from a prompt or a sample file:

# Generate schema from a prompt
generated = client.extract.generate_schema(
    prompt="Extract company financials including revenue, net income, and fiscal year",
)

# Generate schema from a sample file
file_obj = client.files.create(file="sample_report.pdf", purpose="extract")
generated = client.extract.generate_schema(
    file_id=file_obj.id,
    prompt="Extract key financial data",
)

# Use the generated schema in an extraction
job = client.extract.create(
    file_input=file_obj.id,
    configuration={
        "data_schema": generated.parameters.data_schema,
        "tier": "agentic",
    },
)