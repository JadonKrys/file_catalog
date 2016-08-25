# file_catalog
Store file metadata information in a file catalog

## Interface

The primary interface is an HTTP server. TLS and other security
hardening mechanisms are handled by a reverse proxy server as
for normal web applications.

## Browser

Requests to the main url `/` are browsable like a standard website.
They will use javascript to activate the REST API as necessary.

## REST API

Requests with urls of the form `/api/RESOURCE` can access the
REST API. 

### Files

Unique identifiers:

* `file_id`

* `file_name`

  The `file_name` is a logical identifier much like a path in a filesystem.
  It should be human-readable and have some meaning, since this is what
  users see and interact with.

#### /api/files

Resource representing the collection of all files in the catalog.

Operations:

* GET: Obtain list of files

  **Query Parameters**
  
  * limit: (positive integer) number of results to provide
  * start: (non-negative integer) result at which to start at
  * query: (string) query specification
  
  The server SHOULD honor the *start* parameter. The server MAY honor the 
  *limit* parameter. In cases where the server does not honor the *limit* 
  parameter, it should do so by providing fewer resources (*limit* should 
  be considered the client’s upper limit for the number of resources in
  the response).
  
  **Result Codes**
  
  * 200: Response contains collection of file resources
  * 429: Too many requests (if server is being hammered)
  * 500: Unspecified server error
  * 503: Service unavailable (maintenance, etc.)

* POST: Create a new file or add a replica

  If a file exists and the checksum is the same, a replica
  is added. If the checksum is different an error is returned.
  
  **Result Codes**
  
  * 201: Response contains link to newly created file resource
  * 409: Conflict (if the file already exists); includes link to existing file
  * 429: Too many requests (if server is being hammered)
  * 500: Unspecified server error
  * 503: Service unavailable (maintenance, etc.)

* DELETE: Not supported

* PUT: Not supported

* PATCH: Not supported

#### /api/files/{file_id}

Resource representing the metadata for a file in the file catalog.

Operations:

* GET: Obtain file metadata information

  **Result Codes**
  
  * 200: Response contains metadata of file resource
  * 404: Not Found (file resource does not exist)
  * 429: Too many requests (if server is being hammered)
  * 500: Unspecified server error
  * 503: Service unavailable (maintenance, etc.)

* POST: Not supported

* DELETE: Delete the metadata for the file

  **Result Codes**
  
  * 204: No Content (file resource is successfully deleted)
  * 404: Not Found (file resource does not exist)
  * 429: Too many requests (if server is being hammered)
  * 500: Unspecified server error
  * 503: Service unavailable (maintenance, etc.)

* PUT: Fully update/replace file metadata information

  **Result Codes**
  
  * 200: Response indicates metadata of file resource has been updated/replaced
  * 404: Not Found (file resource does not exist) + link to “files” resource for POST
  * 409: Conflict (if updating an outdated resource - use ETAG hash to compare)
  * 429: Too many requests (if server is being hammered)
  * 500: Unspecified server error
  * 503: Service unavailable (maintenance, etc.)

* PATCH: Partially update/replace file metadata information

  The JSON provided as body to PATCH need not contain all the
  keys, only the keys that need to be updated. If a key is
  provided with a value null, then that key can be removed from
  the metadata.

  **Result Codes**
  
  * 200: Response indicates metadata of file resource has been updated/replaced
  * 404: Not Found (file resource does not exist) + link to “files” resource for POST
  * 409: Conflict (if updating an outdated resource - use ETAG hash to compare)
  * 429: Too many requests (if server is being hammered)
  * 500: Unspecified server error
  * 503: Service unavailable (maintenance, etc.)
