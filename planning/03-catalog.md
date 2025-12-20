# Milestone 3: Object Catalog

## Overview
Implement the object catalog management system with full CRUD operations, category management, and image handling.

## Tasks

### 3.1 Backend Catalog API
- [ ] Complete object CRUD endpoints
- [ ] Implement object search with filters
- [ ] Implement pagination
- [ ] Create category CRUD endpoints
- [ ] Implement image upload endpoint
- [ ] Implement image deletion endpoint
- [ ] Add bulk operations

**Implementation Steps:**

1. Object List Endpoint `/api/v1/objects`:
   - Support query parameters: page, page_size, search, category_id, status
   - Return paginated response with total count
   - Include thumbnail URLs

2. Object Create Endpoint:
   - Validate required fields (name)
   - Set owner_id from JWT
   - Return created object

3. Object Update Endpoint:
   - Check ownership
   - Partial updates support
   - Update timestamp

4. Object Delete Endpoint:
   - Check ownership
   - Delete associated images from MinIO
   - Cascade delete images from DB

5. Category Endpoints:
   - GET /categories - List with hierarchy
   - POST /categories - Create category
   - PUT /categories/{id} - Update
   - DELETE /categories/{id} - Delete (check for objects)

### 3.2 Image Management
- [ ] Configure MinIO bucket policies
- [ ] Implement image validation (type, size)
- [ ] Implement image resizing/thumbnails
- [ ] Generate presigned URLs for images
- [ ] Handle image metadata extraction

**Implementation Steps:**

1. Create image processing service:
   ```python
   class ImageService:
       def validate_image(self, file: UploadFile) -> bool
       def resize_image(self, data: bytes, max_size: tuple) -> bytes
       def create_thumbnail(self, data: bytes) -> bytes
       def extract_metadata(self, data: bytes) -> dict
   ```

2. Configure MinIO bucket:
   - Create bucket on startup if not exists
   - Set bucket policy for read access (optional)

3. Image storage structure:
   ```
   objects/{object_id}/
     images/{image_id}.jpg
     thumbnails/{image_id}_thumb.jpg
   ```

### 3.3 Frontend Catalog
- [ ] Create catalog list page
- [ ] Create object detail page
- [ ] Create object form (create/edit)
- [ ] Create category management
- [ ] Implement image upload component
- [ ] Implement image gallery component

**Implementation Steps:**

1. Catalog List Page:
   - Search bar with debounce
   - Filter by category dropdown
   - Status filter tabs
   - Card grid with thumbnails
   - Pagination controls
   - Add object button

2. Object Detail Page:
   - Image gallery with lightbox
   - Metadata display
   - Edit/Delete buttons
   - Training status badge
   - Category breadcrumb

3. Object Form:
   - Name, description, reference fields
   - Category selector
   - Physical properties (weight, dimensions)
   - Commercial properties (price, color)
   - Materials multi-select
   - Image drop zone
   - Image preview with delete

4. Image Upload Component:
   - Drag and drop zone
   - File input fallback
   - Preview thumbnails
   - Upload progress
   - Remove button
   - Primary image selection

### 3.4 API Service Integration
- [ ] Create objects API service
- [ ] Create categories API service
- [ ] Create object store
- [ ] Implement optimistic updates
- [ ] Handle error states

**Implementation Steps:**

1. Create `core/api/objects-api.service.ts`:
   ```typescript
   @Injectable({ providedIn: 'root' })
   export class ObjectsApiService {
     list(params: ObjectListParams): Observable<PaginatedResponse<ObjectListItem>>
     get(id: string): Observable<ObjectDetail>
     create(data: ObjectCreate): Observable<ObjectDetail>
     update(id: string, data: ObjectUpdate): Observable<ObjectDetail>
     delete(id: string): Observable<void>
     uploadImage(objectId: string, file: File): Observable<ImageUploadResponse>
     deleteImage(objectId: string, imageId: string): Observable<void>
   }
   ```

2. Create `core/state/catalog.store.ts`:
   - objects signal
   - currentObject signal
   - categories signal
   - loading states
   - error handling

## Verification Checklist

- [ ] Objects can be created with all metadata
- [ ] Objects list displays with pagination
- [ ] Search filters objects correctly
- [ ] Category filter works
- [ ] Objects can be edited
- [ ] Objects can be deleted
- [ ] Images upload successfully
- [ ] Thumbnails display correctly
- [ ] Primary image can be set
- [ ] Images can be deleted
- [ ] Categories can be managed
- [ ] Proper error messages display

## API Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | /api/v1/objects | List objects | Yes |
| POST | /api/v1/objects | Create object | Yes |
| GET | /api/v1/objects/{id} | Get object | Yes |
| PUT | /api/v1/objects/{id} | Update object | Yes |
| DELETE | /api/v1/objects/{id} | Delete object | Yes |
| POST | /api/v1/objects/{id}/images | Upload image | Yes |
| GET | /api/v1/objects/{id}/images | List images | Yes |
| DELETE | /api/v1/objects/{id}/images/{imageId} | Delete image | Yes |
| GET | /api/v1/categories | List categories | Yes |
| POST | /api/v1/categories | Create category | Yes |
| PUT | /api/v1/categories/{id} | Update category | Yes |
| DELETE | /api/v1/categories/{id} | Delete category | Yes |

## Next Steps
After completing the catalog, proceed to Milestone 4: Object Learning.
