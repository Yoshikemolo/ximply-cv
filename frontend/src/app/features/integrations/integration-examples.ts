/**
 * Ready to paste examples for the Integrations page.
 *
 * Kept out of the component because they are content, not behaviour, and a
 * component that has to be read past four hundred lines of sample code to find
 * its logic is a component nobody will maintain.
 *
 * Every receiver example verifies the signature before trusting the body. That
 * is not decoration: an endpoint that accepts any POST it receives is an
 * endpoint anyone on the network can feed, and showing an example without the
 * check would teach exactly the wrong thing.
 */

/** One selectable example. */
export interface Example {
  id: string;
  label: string;
  language: string;
  caption: string;
  code: string;
}

/**
 * Build the webhook receiver examples.
 *
 * @param secret - The secret to show, when one has just been issued.
 */
export function webhookExamples(secret: string): Example[] {
  const shown = secret || 'YOUR_WEBHOOK_SECRET';

  return [
    {
      id: 'node',
      label: 'Node.js',
      language: 'javascript',
      caption: 'server.js',
      code: `const express = require("express");
const crypto = require("crypto");

const app = express();
const SECRET = process.env.XIMPLY_SECRET || "${shown}";

// The raw body is required: the signature covers the exact bytes that were
// sent, so any re-serialisation invalidates it.
app.post(
  "/ximply/events",
  express.raw({ type: "application/json" }),
  (req, res) => {
    const signature = req.get("X-Ximply-Signature") || "";
    const timestamp = req.get("X-Ximply-Timestamp") || "";

    // Reject anything older than five minutes, so a captured request cannot be
    // replayed indefinitely.
    if (Math.abs(Date.now() / 1000 - Number(timestamp)) > 300) {
      return res.status(408).send("stale");
    }

    const expected =
      "sha256=" +
      crypto
        .createHmac("sha256", SECRET)
        .update(Buffer.concat([Buffer.from(timestamp + "."), req.body]))
        .digest("hex");

    // Constant time, so a wrong signature cannot be found byte by byte.
    const ok =
      expected.length === signature.length &&
      crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(signature));

    if (!ok) {
      return res.status(401).send("bad signature");
    }

    const event = JSON.parse(req.body.toString("utf8"));
    console.log(event.eventName, event.attributes["ximply.subject.name"]);

    // Answer quickly. A slow reply is retried, and the same event arrives twice.
    res.sendStatus(204);
  }
);

app.listen(3000);`,
    },
    {
      id: 'nestjs',
      label: 'NestJS',
      language: 'typescript',
      caption: 'ximply.controller.ts',
      code: `import { Controller, Post, Req, Headers, HttpCode, UnauthorizedException } from "@nestjs/common";
import { createHmac, timingSafeEqual } from "crypto";
import type { Request } from "express";

const SECRET = process.env.XIMPLY_SECRET ?? "${shown}";

@Controller("ximply")
export class XimplyController {
  @Post("events")
  @HttpCode(204)
  handle(
    @Req() request: Request,
    @Headers("x-ximply-signature") signature: string,
    @Headers("x-ximply-timestamp") timestamp: string,
  ): void {
    // Configure the raw body in main.ts:
    //   app.use("/ximply/events", raw({ type: "application/json" }));
    const body = request.body as Buffer;

    if (Math.abs(Date.now() / 1000 - Number(timestamp)) > 300) {
      throw new UnauthorizedException("Stale delivery");
    }

    const expected =
      "sha256=" +
      createHmac("sha256", SECRET)
        .update(Buffer.concat([Buffer.from(timestamp + "."), body]))
        .digest("hex");

    if (
      expected.length !== signature?.length ||
      !timingSafeEqual(Buffer.from(expected), Buffer.from(signature))
    ) {
      throw new UnauthorizedException("Invalid signature");
    }

    const event = JSON.parse(body.toString("utf8"));
    console.log(event.eventName, event.body);
  }
}`,
    },
    {
      id: 'python',
      label: 'Python',
      language: 'python',
      caption: 'receiver.py',
      code: `import hashlib
import hmac
import time

from fastapi import FastAPI, Header, HTTPException, Request

app = FastAPI()
SECRET = "${shown}"


@app.post("/ximply/events", status_code=204)
async def receive(
    request: Request,
    x_ximply_signature: str = Header(""),
    x_ximply_timestamp: str = Header(""),
):
    # The raw body, not the parsed one: the signature covers these bytes.
    body = await request.body()

    try:
        age = abs(time.time() - float(x_ximply_timestamp))
    except ValueError:
        raise HTTPException(status_code=401, detail="Bad timestamp")

    # Anything older than five minutes is a replay, not a delivery.
    if age > 300:
        raise HTTPException(status_code=408, detail="Stale delivery")

    material = x_ximply_timestamp.encode() + b"." + body
    digest = hmac.new(SECRET.encode(), material, hashlib.sha256).hexdigest()

    # Constant time, so a wrong signature cannot be discovered from timing.
    if not hmac.compare_digest(f"sha256={digest}", x_ximply_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = await request.json()
    print(event["eventName"], event["attributes"].get("ximply.subject.name"))`,
    },
    {
      id: 'spring',
      label: 'Java Spring',
      language: 'java',
      caption: 'XimplyWebhookController.java',
      code: `package com.example.ximply;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class XimplyWebhookController {

    private static final String SECRET = "${shown}";
    private static final long TOLERANCE_SECONDS = 300;

    // byte[] rather than a mapped type: the signature covers the exact bytes,
    // so letting the framework parse and re-serialise would break it.
    @PostMapping("/ximply/events")
    public ResponseEntity<Void> receive(
            @RequestBody byte[] body,
            @RequestHeader("X-Ximply-Signature") String signature,
            @RequestHeader("X-Ximply-Timestamp") String timestamp) throws Exception {

        long age = Math.abs(System.currentTimeMillis() / 1000 - Long.parseLong(timestamp));
        if (age > TOLERANCE_SECONDS) {
            return ResponseEntity.status(HttpStatus.REQUEST_TIMEOUT).build();
        }

        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(SECRET.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        mac.update((timestamp + ".").getBytes(StandardCharsets.UTF_8));
        byte[] digest = mac.doFinal(body);

        StringBuilder expected = new StringBuilder("sha256=");
        for (byte b : digest) {
            expected.append(String.format("%02x", b));
        }

        // MessageDigest.isEqual is the constant time comparison here.
        boolean ok = MessageDigest.isEqual(
                expected.toString().getBytes(StandardCharsets.UTF_8),
                signature.getBytes(StandardCharsets.UTF_8));

        if (!ok) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
        }

        System.out.println(new String(body, StandardCharsets.UTF_8));
        return ResponseEntity.noContent().build();
    }
}`,
    },
    {
      id: 'dotnet',
      label: '.NET 9',
      language: 'csharp',
      caption: 'Program.cs',
      code: `using System.Security.Cryptography;
using System.Text;

var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();

const string Secret = "${shown}";
const long ToleranceSeconds = 300;

app.MapPost("/ximply/events", async (HttpRequest request) =>
{
    // Read the raw body: the signature covers these exact bytes, so binding to
    // a model and re-serialising would invalidate it.
    using var reader = new StreamReader(request.Body);
    var raw = await reader.ReadToEndAsync();
    var body = Encoding.UTF8.GetBytes(raw);

    var signature = request.Headers["X-Ximply-Signature"].ToString();
    var timestamp = request.Headers["X-Ximply-Timestamp"].ToString();

    if (!long.TryParse(timestamp, out var sent))
    {
        return Results.Unauthorized();
    }

    var age = Math.Abs(DateTimeOffset.UtcNow.ToUnixTimeSeconds() - sent);
    if (age > ToleranceSeconds)
    {
        return Results.StatusCode(StatusCodes.Status408RequestTimeout);
    }

    using var mac = new HMACSHA256(Encoding.UTF8.GetBytes(Secret));
    var material = Encoding.UTF8.GetBytes(timestamp + ".").Concat(body).ToArray();
    var expected = "sha256=" + Convert.ToHexString(mac.ComputeHash(material)).ToLowerInvariant();

    // Fixed time comparison, so timing reveals nothing about the signature.
    var ok = CryptographicOperations.FixedTimeEquals(
        Encoding.UTF8.GetBytes(expected),
        Encoding.UTF8.GetBytes(signature));

    if (!ok)
    {
        return Results.Unauthorized();
    }

    Console.WriteLine(raw);
    return Results.NoContent();
});

app.Run();`,
    },
  ];
}

/**
 * Build the protocol client configuration examples.
 *
 * @param baseUrl - Where this instance is reachable from the agent's machine.
 * @param token - The integration token to show, when one has just been issued.
 */
export function mcpExamples(baseUrl: string, token: string): Example[] {
  const shown = token || 'YOUR_INTEGRATION_TOKEN';

  return [
    {
      id: 'claude',
      label: 'Claude',
      language: 'json',
      caption: 'claude_desktop_config.json',
      code: `{
  "mcpServers": {
    "ximply-vision": {
      "type": "http",
      "url": "${baseUrl}/mcp",
      "headers": {
        "Authorization": "Bearer ${shown}"
      }
    }
  }
}`,
    },
    {
      id: 'chatgpt',
      label: 'ChatGPT',
      language: 'json',
      caption: 'Connector configuration',
      code: `{
  "name": "XIMPLY Vision",
  "description": "Read what the camera has observed",
  "transport": {
    "type": "streamable_http",
    "url": "${baseUrl}/mcp"
  },
  "authentication": {
    "type": "bearer",
    "token": "${shown}"
  }
}`,
    },
    {
      id: 'gemini',
      label: 'Gemini',
      language: 'json',
      caption: 'settings.json',
      code: `{
  "mcpServers": {
    "ximply-vision": {
      "httpUrl": "${baseUrl}/mcp",
      "headers": {
        "Authorization": "Bearer ${shown}"
      },
      "timeout": 30000
    }
  }
}`,
    },
    {
      id: 'sse',
      label: 'Server sent events',
      language: 'json',
      caption: 'For clients that predate streamable HTTP',
      code: `{
  "mcpServers": {
    "ximply-vision": {
      "type": "sse",
      "url": "${baseUrl}/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${shown}"
      }
    }
  }
}`,
    },
    {
      id: 'curl',
      label: 'Any client',
      language: 'bash',
      caption: 'Check the connection before configuring an agent',
      code: `# Open a session. The response carries an mcp-session-id header.
curl -i -X POST ${baseUrl}/mcp/ \\
  -H "Authorization: Bearer ${shown}" \\
  -H "Content-Type: application/json" \\
  -H "Accept: application/json, text/event-stream" \\
  -d '{
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
          "protocolVersion": "2025-06-18",
          "capabilities": {},
          "clientInfo": { "name": "curl", "version": "1" }
        }
      }'

# Then list the tools, passing the session id back.
curl -X POST ${baseUrl}/mcp/ \\
  -H "Authorization: Bearer ${shown}" \\
  -H "mcp-session-id: SESSION_ID_FROM_ABOVE" \\
  -H "Content-Type: application/json" \\
  -H "Accept: application/json, text/event-stream" \\
  -d '{ "jsonrpc": "2.0", "id": 2, "method": "tools/list" }'`,
    },
    {
      id: 'camera',
      label: 'Camera',
      language: 'bash',
      caption: 'Ask the camera to start. Needs camera:control on the token',
      code: `# The reply says what happened, not what was asked for. "pending": true
# means the request was recorded and no view is open to honour it, so the
# camera has not started. It starts when someone opens the view.
curl -X POST ${baseUrl}/mcp/ \
  -H "Authorization: Bearer ${shown}" \
  -H "mcp-session-id: SESSION_ID_FROM_ABOVE" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
          "name": "start_camera",
          "arguments": { "camera_id": "default" }
        }
      }'

# Whether it is actually running is a separate question, decided by frames
# arriving rather than by anything asserting it.
curl -X POST ${baseUrl}/mcp/ \
  -H "Authorization: Bearer ${shown}" \
  -H "mcp-session-id: SESSION_ID_FROM_ABOVE" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": { "name": "get_camera", "arguments": {} }
      }'`,
    },
  ];
}

/**
 * Build the streaming client examples.
 *
 * The browser examples read the stream with fetch and a reader rather than with
 * EventSource. EventSource sends no Authorization header and the endpoint
 * refuses a token in the query string on purpose, so there is no other way in.
 *
 * They also normalise the line endings before framing. The server separates
 * messages with a carriage return and a line feed, and a reader that looks for
 * two line feeds alone finds nothing at all.
 *
 * @param baseUrl - Where this instance is reachable from the client's machine.
 * @param token - The integration token to show, when one has just been issued.
 */
export function streamExamples(baseUrl: string, token: string): Example[] {
  const shown = token || 'YOUR_INTEGRATION_TOKEN';

  return [
    {
      id: 'shell',
      label: 'Shell',
      language: 'bash',
      caption: 'Nothing to write',
      code: `# Every record on the broker, the status topic included. Host and port are in
# the table above; add -u and -P when the broker asks for an account.
mosquitto_sub -h localhost -p 1883 -t 'ximply/#' -v

# The same events over HTTP, with no broker deployed at all. -N holds the
# connection open, so each record prints as it is raised.
curl -N -H "Authorization: Bearer ${shown}" \\
  ${baseUrl}/api/v1/stream/events

# Watch a camera. The stream is multipart JPEG, which ffplay reads directly.
# The header needs its own line ending, hence the quoting.
ffplay -headers $'Authorization: Bearer ${shown}\\r\\n' \\
  ${baseUrl}/api/v1/stream/camera/default`,
    },
    {
      id: 'javascript',
      label: 'JavaScript',
      language: 'javascript',
      caption: 'stream.js',
      code: `// EventSource cannot be used here: it sends no Authorization header, and the
// endpoint refuses a token in the query string on purpose.
const BASE_URL = "${baseUrl}";
const TOKEN = "${shown}";

async function streamEvents(onEvent, signal) {
  const response = await fetch(\`\${BASE_URL}/api/v1/stream/events\`, {
    headers: { Authorization: \`Bearer \${TOKEN}\`, Accept: "text/event-stream" },
    signal,
  });
  if (!response.ok) {
    throw new Error(\`Stream refused: \${response.status}\`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    // The server ends every line with a carriage return and a line feed. A
    // reader that frames on two line feeds alone never finds a message.
    buffer += decoder.decode(value, { stream: true }).replace(/\\r\\n/g, "\\n");

    let end = buffer.indexOf("\\n\\n");
    while (end !== -1) {
      handleMessage(buffer.slice(0, end), onEvent);
      buffer = buffer.slice(end + 2);
      end = buffer.indexOf("\\n\\n");
    }
  }
}

function handleMessage(message, onEvent) {
  let type = "message";
  const data = [];

  for (const line of message.split("\\n")) {
    // A line starting with a colon is the keepalive comment, sent so an idle
    // connection survives a proxy. There is nothing in it.
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) type = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trim());
  }

  if (data.length > 0) {
    onEvent(type, JSON.parse(data.join("\\n")));
  }
}

const controller = new AbortController();
streamEvents((type, event) => {
  console.log(type, event.body);
}, controller.signal);
// controller.abort() closes it. The server notices and ends the generator.`,
    },
    {
      id: 'react',
      label: 'React',
      language: 'javascript',
      caption: 'useVisionEvents.jsx',
      code: `import { useEffect, useState } from "react";

const BASE_URL = "${baseUrl}";
const TOKEN = "${shown}";

// Events. The abort controller is the cleanup: without it a remounted
// component leaves the previous connection open on the server.
export function useVisionEvents() {
  const [events, setEvents] = useState([]);

  useEffect(() => {
    const controller = new AbortController();

    (async () => {
      const response = await fetch(\`\${BASE_URL}/api/v1/stream/events\`, {
        headers: { Authorization: \`Bearer \${TOKEN}\` },
        signal: controller.signal,
      });
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        // Line endings are normalised before framing: the server writes a
        // carriage return and a line feed, not a bare line feed.
        buffer += decoder.decode(value, { stream: true }).replace(/\\r\\n/g, "\\n");

        let end = buffer.indexOf("\\n\\n");
        while (end !== -1) {
          const lines = buffer.slice(0, end).split("\\n");
          buffer = buffer.slice(end + 2);
          end = buffer.indexOf("\\n\\n");

          const data = lines
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trim());
          if (data.length > 0) {
            setEvents((seen) => [JSON.parse(data.join("\\n")), ...seen]);
          }
        }
      }
    })().catch((error) => {
      if (error.name !== "AbortError") console.error(error);
    });

    return () => controller.abort();
  }, []);

  return events;
}

// The camera. An img tag cannot be pointed at the stream, because it cannot
// send the header the credential travels in. Read the multipart body instead
// and hand each part to the img as a blob URL, revoking the one before it.
export function useCameraFrame(cameraId = "default") {
  const [src, setSrc] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    let current = null;

    (async () => {
      const response = await fetch(
        \`\${BASE_URL}/api/v1/stream/camera/\${cameraId}\`,
        {
          headers: { Authorization: \`Bearer \${TOKEN}\` },
          signal: controller.signal,
        }
      );
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = new Uint8Array();

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        const merged = new Uint8Array(buffer.length + value.length);
        merged.set(buffer);
        merged.set(value, buffer.length);
        buffer = merged;

        // Each part is framed by its own headers, and the server writes a
        // Content-Length on every one. Trusting that is what makes this
        // correct: scanning for the end-of-image marker instead would cut a
        // frame short the moment a JPEG carried an embedded thumbnail.
        while (true) {
          const headerEnd = indexOfHeaderEnd(buffer);
          if (headerEnd === -1) break;

          const headers = decoder.decode(buffer.slice(0, headerEnd));
          const match = headers.match(/Content-Length:\\s*(\\d+)/i);
          if (!match) break;

          const length = Number(match[1]);
          const start = headerEnd + 4;
          if (buffer.length < start + length) break;

          const frame = buffer.slice(start, start + length);
          buffer = buffer.slice(start + length);

          if (current) URL.revokeObjectURL(current);
          current = URL.createObjectURL(
            new Blob([frame], { type: "image/jpeg" })
          );
          setSrc(current);
        }
      }
    })().catch((error) => {
      if (error.name !== "AbortError") console.error(error);
    });

    return () => {
      controller.abort();
      if (current) URL.revokeObjectURL(current);
    };
  }, [cameraId]);

  return src;
}

// The blank line between a part's headers and its bytes.
function indexOfHeaderEnd(bytes) {
  for (let i = 0; i < bytes.length - 3; i += 1) {
    if (
      bytes[i] === 13 &&
      bytes[i + 1] === 10 &&
      bytes[i + 2] === 13 &&
      bytes[i + 3] === 10
    ) {
      return i;
    }
  }
  return -1;
}

// Then in a component: <img src={useCameraFrame()} alt="" />`,
    },
    {
      id: 'angular',
      label: 'Angular',
      language: 'typescript',
      caption: 'vision-stream.service.ts',
      code: `import { DestroyRef, Injectable, inject, signal } from '@angular/core';

const BASE_URL = '${baseUrl}';
const TOKEN = '${shown}';

/** One event, as the stream delivers it. */
export interface StreamedEvent {
  id: string;
  eventName: string;
  body: Record<string, unknown>;
  attributes: Record<string, unknown>;
  occurredAt: string | null;
}

@Injectable({ providedIn: 'root' })
export class VisionStreamService {
  /** The events received so far, newest first. */
  readonly events = signal<StreamedEvent[]>([]);

  /** Whether the connection is currently open. */
  readonly connected = signal(false);

  private readonly controller = new AbortController();

  constructor() {
    inject(DestroyRef).onDestroy(() => this.controller.abort());
    void this.listen();
  }

  private async listen(): Promise<void> {
    const response = await fetch(\`\${BASE_URL}/api/v1/stream/events\`, {
      headers: { Authorization: \`Bearer \${TOKEN}\` },
      signal: this.controller.signal,
    });
    if (!response.body) {
      return;
    }
    this.connected.set(true);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }

        // The server writes a carriage return and a line feed. Normalising
        // here is what makes the blank line separator findable.
        buffer += decoder.decode(value, { stream: true }).replace(/\\r\\n/g, '\\n');

        let end = buffer.indexOf('\\n\\n');
        while (end !== -1) {
          this.accept(buffer.slice(0, end));
          buffer = buffer.slice(end + 2);
          end = buffer.indexOf('\\n\\n');
        }
      }
    } finally {
      this.connected.set(false);
    }
  }

  private accept(message: string): void {
    const data = message
      .split('\\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trim());

    if (data.length === 0) {
      return;
    }
    const event = JSON.parse(data.join('\\n')) as StreamedEvent;
    this.events.update((seen) => [event, ...seen]);
  }
}`,
    },
  ];
}
