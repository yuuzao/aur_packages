import { ServerResponse } from "node:http";

function relaxCookie(value) {
  if (typeof value !== "string" || !value.startsWith("dsh-auth-")) return value;
  if (value.includes("; SameSite=Lax")) return value;
  const strict = "; SameSite=Strict";
  if (!value.includes(strict)) {
    throw new Error("dsh-web: dsh-auth cookie is missing SameSite=Strict");
  }
  return value.replace(strict, "; SameSite=Lax");
}

function relaxHeaderValue(name, value) {
  if (name.toLowerCase() !== "set-cookie") return value;
  if (Array.isArray(value)) return value.map(relaxCookie);
  return relaxCookie(value);
}

function relaxHeaders(headers) {
  if (Array.isArray(headers)) {
    for (const entry of headers) {
      if (!Array.isArray(entry) || entry.length < 2 || typeof entry[0] !== "string") {
        throw new Error("dsh-web: writeHead header entry is not a name/value pair");
      }
      entry[1] = relaxHeaderValue(entry[0], entry[1]);
    }
    return;
  }
  if (typeof headers !== "object" || headers === null) {
    throw new Error("dsh-web: writeHead headers are missing");
  }
  for (const key of Object.keys(headers)) {
    headers[key] = relaxHeaderValue(key, headers[key]);
  }
}

if (typeof ServerResponse.prototype.appendHeader !== "function") {
  throw new Error("dsh-web: ServerResponse.appendHeader is missing");
}

const originalWriteHead = ServerResponse.prototype.writeHead;
ServerResponse.prototype.writeHead = function (statusCode, statusMessage, headers) {
  if (typeof statusMessage === "string") {
    if (headers !== undefined) relaxHeaders(headers);
  } else if (statusMessage !== undefined) {
    relaxHeaders(statusMessage);
  }
  return originalWriteHead.apply(this, arguments);
};

const originalSetHeader = ServerResponse.prototype.setHeader;
ServerResponse.prototype.setHeader = function (name, value) {
  return originalSetHeader.call(this, name, relaxHeaderValue(String(name), value));
};

const originalAppendHeader = ServerResponse.prototype.appendHeader;
ServerResponse.prototype.appendHeader = function (name, value) {
  return originalAppendHeader.call(this, name, relaxHeaderValue(String(name), value));
};
