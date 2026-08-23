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
