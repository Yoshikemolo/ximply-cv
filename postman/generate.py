"""Rebuild the Postman collection from the OpenAPI document the server publishes.

Run from the repository root, with the application running:

    curl -s http://localhost:8000/api/v1/openapi.json -o openapi.json
    python postman/generate.py openapi.json


The collection had drifted to describing thirty of the sixty-one operations the
application serves, and one of those thirty sent a JSON body to a route that
reads query parameters. Nothing kept the two in step, and nothing was going to.

Generating it removes the drift at its source: a route added to a router appears
here without anybody remembering to add it, and a route whose shape changes
cannot keep an example that no longer matches.

Two things are not generated, because a document cannot supply them. EXAMPLES
holds request bodies written by hand, since a schema walk produces a shape that
is correct and useless: "string" tells a reader nothing about what belongs
there. NOTES holds descriptions for routes whose summary does not explain what
they are for. Anything else in the previous collection is carried over when its
path and method still exist, and dropped when they do not.
"""

import json
import re
import sys
from collections import OrderedDict

COLLECTION = "postman/ximply-vision.postman_collection.json"
PREFIX = "/api/v1"

# Tag to folder, in the order a reader should meet them.
FOLDERS = [
    ("Health", "Health"),
    ("Authentication", "Authentication"),
    ("Detection", "Detection"),
    ("Objects", "Objects"),
    ("Events", "Events"),
    ("Webhooks", "Webhooks"),
    ("Integrations", "Integration tokens"),
    ("Users", "Users (Admin)"),
]

# Paths whose purpose is not obvious from the summary alone.
NOTES = {
    ("GET", "/detection/camera"): (
        "The state a camera is wanted in, and whether it is actually running. "
        "'running' is decided by frames arriving for detection, never by what "
        "was asked for, so 'pending' true means the request was recorded and no "
        "view is open to honour it. Needs detection:view."
    ),
    ("PUT", "/detection/camera"): (
        "Ask a camera to start or stop. The camera belongs to the browser, so "
        "this records a request that an open view honours. Needs "
        "camera:control, which has to be named on the token."
    ),
    ("GET", "/health/mcp"): (
        "Whether the Model Context Protocol is built into this deployment "
        "('available', set by MCP_ENABLED and read at startup) and whether it "
        "is currently open ('enabled', the runtime switch behind the footer "
        "control). Public."
    ),
    ("PUT", "/health/mcp"): (
        "Open or close the protocol without restarting. A closed protocol keeps "
        "both transports mounted and answers 503, so a connected agent gets an "
        "answer rather than a hole. Needs events:manage. A deployment started "
        "without the protocol answers 409."
    ),
    ("GET", "/events"): (
        "Events newest first. 'since' is the polling contract: ask for "
        "everything after the last event already seen. It compares against "
        "occurredAt, which is the moment of the observation."
    ),
    ("GET", "/events/{event_id}/capture"): (
        "The frame that produced an event. Behind the read permission, unlike "
        "the catalog image proxy, because it is a photograph of whoever was in "
        "front of the camera."
    ),
    ("DELETE", "/events/prune"): (
        "Deletes everything older than the cutoff. Nothing prunes events on its "
        "own, so a deployment with a retention obligation calls this on a "
        "schedule of its own."
    ),
    ("POST", "/integration-tokens"): (
        "The value is shown in this response and never again. Scopes may not "
        "exceed what the issuing user holds. camera:control has to be named "
        "here to be usable: it is never inherited from an empty scope list."
    ),
    ("PUT", "/health/acceleration"): (
        "Move one inference backend between the processor and the accelerator. "
        "The models affected are dropped and rebuild on the next frame."
    ),
}


# Bodies worth writing by hand. A schema walk produces a shape that is correct
# and useless: "string" tells a reader nothing about what belongs there.
EXAMPLES = {
    ("POST", "/detection/detect"): {
        "image": "data:image/jpeg;base64,REPLACE_WITH_A_BASE64_FRAME",
        "confidenceThreshold": 0.5,
        "iouThreshold": 0.45,
        "hidePersonDetections": False,
        "showOnlyCustomObjects": False,
        "includeSkeletons": True,
        "includeFaceMesh": True,
        "detectionModel": "yolo",
        "cameraId": "default",
    },
    ("POST", "/detection/describe"): {
        "image": "data:image/jpeg;base64,REPLACE_WITH_A_BASE64_FRAME",
        "detections": [],
    },
    ("POST", "/detection/capture"): {
        "image": "data:image/jpeg;base64,REPLACE_WITH_A_BASE64_FRAME",
        "bbox": {"x": 100, "y": 80, "width": 220, "height": 180},
        "name": "Stapler",
        "description": "Captured from the live view",
    },
    ("POST", "/webhooks"): {
        "name": "Door notifier",
        "url": "https://example.invalid/hooks/ximply",
        "eventTypes": ["person.enrolled", "person.recognised"],
    },
    ("PUT", "/webhooks/{subscription_id}"): {
        "name": "Door notifier",
        "eventTypes": ["person.recognised"],
        "isActive": True,
    },
    ("POST", "/integration-tokens"): {
        "name": "Reading agent",
        "scopes": ["events:read", "objects:read"],
        "expiresInDays": 90,
    },
    ("POST", "/objects"): {
        "name": "Stapler",
        "description": "Black, office",
        "reference": "SKU-0001",
        "weight": 0.4,
    },
    ("POST", "/objects/merge"): {
        "sourceId": "{{object_id}}",
        "targetId": "{{object_id}}",
    },
    ("PATCH", "/objects/{object_id}/name"): {"name": "Stapler"},
    ("POST", "/users"): {
        "email": "operator@example.invalid",
        "password": "replace-me",
        "fullName": "Operator",
        "roles": ["operator"],
    },
    ("POST", "/auth/register"): {
        "email": "operator@example.invalid",
        "password": "replace-me",
        "fullName": "Operator",
    },
}


def load_openapi(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def existing_bodies(collection):
    """Hand-written request bodies from the collection being replaced."""
    bodies = {}

    def walk(items):
        for item in items:
            if "item" in item:
                walk(item["item"])
                continue
            request = item.get("request") or {}
            url = request.get("url") or {}
            raw = url.get("raw", "")
            path = raw.replace("{{baseUrl}}", "").split("?")[0]
            body = (request.get("body") or {}).get("raw")
            if body:
                bodies[(request.get("method"), path)] = body

    walk(collection["item"])
    return bodies


def resolve(schema, spec, depth=0):
    """A small example value for a schema, following one level of references."""
    if depth > 4 or not isinstance(schema, dict):
        return None

    ref = schema.get("$ref")
    if ref:
        name = ref.rsplit("/", 1)[-1]
        target = spec["components"]["schemas"].get(name, {})
        return resolve(target, spec, depth + 1)

    for key in ("allOf", "anyOf", "oneOf"):
        if key in schema:
            for option in schema[key]:
                if option.get("type") != "null":
                    return resolve(option, spec, depth + 1)

    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]

    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        required = set(schema.get("required", []))
        out = OrderedDict()
        for name, sub in (schema.get("properties") or {}).items():
            if required and name not in required:
                continue
            out[name] = resolve(sub, spec, depth + 1)
        return out
    if kind == "array":
        inner = resolve(schema.get("items", {}), spec, depth + 1)
        return [inner] if inner is not None else []
    if kind == "integer":
        return 0
    if kind == "number":
        return 0.0
    if kind == "boolean":
        return True
    if kind == "string":
        fmt = schema.get("format")
        if fmt == "uuid":
            return "{{objectId}}"
        if fmt == "date-time":
            return "2026-01-01T00:00:00Z"
        if schema.get("enum"):
            return schema["enum"][0]
        return "string"
    return None


def query_value(example):
    """
    A query parameter as it travels on a URL.

    Python spells its booleans with a capital, and a server reading "True" from
    a query string is reading a word it did not ask for.
    """
    if example is None or example == "string":
        return ""
    if isinstance(example, bool):
        return "true" if example else "false"
    return str(example)


def path_segments(path):
    return [s for s in path.strip("/").split("/") if s]


def to_postman_path(path):
    """Postman writes a path parameter as :name rather than {name}."""
    return re.sub(r"\{([^}]+)\}", r":\1", path)


def build_item(method, path, operation, spec, carried):
    trimmed = path[len(PREFIX):] if path.startswith(PREFIX) else path
    postman_path = to_postman_path(trimmed)

    query = []
    variables = []
    for param in operation.get("parameters", []):
        if param.get("$ref"):
            continue
        where = param.get("in")
        example = resolve(param.get("schema", {}), spec)
        if where == "query":
            query.append(
                OrderedDict(
                    [
                        ("key", param["name"]),
                        ("value", query_value(example)),
                        ("description", param.get("description", "")),
                        ("disabled", not param.get("required", False)),
                    ]
                )
            )
        elif where == "path":
            variables.append(
                OrderedDict(
                    [("key", param["name"]), ("value", f"{{{{{param['name']}}}}}")]
                )
            )

    raw = "{{baseUrl}}" + postman_path
    if query:
        enabled = [q for q in query if not q["disabled"]]
        if enabled:
            raw += "?" + "&".join(f"{q['key']}={q['value']}" for q in enabled)

    url = OrderedDict([("raw", raw), ("host", ["{{baseUrl}}"]), ("path", path_segments(postman_path))])
    if query:
        url["query"] = query
    if variables:
        url["variable"] = variables

    headers = []
    body = None
    request_body = operation.get("requestBody")
    if request_body:
        content = request_body.get("content", {})
        if "application/json" in content:
            written = EXAMPLES.get((method, trimmed))
            carried_body = carried.get((method, trimmed))
            if written is not None:
                text = json.dumps(written, indent=2)
            elif carried_body:
                text = carried_body
            else:
                example = resolve(content["application/json"].get("schema", {}), spec)
                text = json.dumps(example, indent=2) if example is not None else "{}"
            headers.append(OrderedDict([("key", "Content-Type"), ("value", "application/json")]))
            body = OrderedDict([("mode", "raw"), ("raw", text)])
        elif "multipart/form-data" in content:
            body = OrderedDict([("mode", "formdata"), ("formdata", [
                OrderedDict([("key", "file"), ("type", "file"), ("src", [])])
            ])])

    description = NOTES.get((method, trimmed)) or operation.get("description") or ""
    description = description.strip().split("\n\n")[0].replace("\n", " ").strip()

    request = OrderedDict([("method", method), ("header", headers)])
    if description:
        request["description"] = description
    if body:
        request["body"] = body
    request["url"] = url

    name = operation.get("summary") or f"{method} {trimmed}"
    return OrderedDict([("name", name.strip()), ("request", request)])


def main():
    spec = load_openapi(sys.argv[1])
    with open(COLLECTION, encoding="utf-8") as f:
        previous = json.load(f)

    carried = existing_bodies(previous)

    buckets = {label: [] for _, label in FOLDERS}
    tag_to_label = {tag: label for tag, label in FOLDERS}
    orphans = []

    for path, operations in spec["paths"].items():
        if not path.startswith(PREFIX):
            continue
        for method, operation in operations.items():
            if method.upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                continue
            item = build_item(method.upper(), path, operation, spec, carried)
            tags = operation.get("tags") or []
            label = next((tag_to_label[t] for t in tags if t in tag_to_label), None)
            (buckets[label] if label else orphans).append((path, method, item))

    if orphans:
        raise SystemExit(f"untagged operations: {[(p, m) for p, m, _ in orphans]}")

    items = []
    for _, label in FOLDERS:
        entries = sorted(buckets[label], key=lambda e: (e[0].count("{"), e[0], e[1]))
        items.append(OrderedDict([("name", label), ("item", [e[2] for e in entries])]))

    referenced = sorted(
        {
            variable["key"]
            for _, label in FOLDERS
            for _, _, item in buckets[label]
            for variable in item["request"]["url"].get("variable", [])
        }
    )
    declared = {v["key"] for v in previous["variable"]}
    variables = list(previous["variable"]) + [
        OrderedDict([("key", key), ("value", ""), ("type", "string")])
        for key in referenced
        if key not in declared
    ]

    collection = OrderedDict(
        [
            ("info", previous["info"]),
            ("variable", variables),
            ("auth", previous["auth"]),
            ("item", items),
        ]
    )

    with open(COLLECTION, "w", encoding="utf-8", newline="\n") as f:
        json.dump(collection, f, ensure_ascii=False, indent=2)
        f.write("\n")

    total = sum(len(f["item"]) for f in items)
    print(f"{total} operations across {len(items)} folders")
    for folder in items:
        print(f"  {folder['name']}: {len(folder['item'])}")


main()
