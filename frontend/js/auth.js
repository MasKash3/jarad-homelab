import { storageKeys } from './config.js';

export async function verifyFingerprint() {
  if (!window.isSecureContext) {
    throw new Error("Fingerprint requires HTTPS or localhost. Use your HTTPS/HTTPS URL for biometric auth.");
  }
  if (!window.PublicKeyCredential || !navigator.credentials) {
    throw new Error("Fingerprint is not available in this browser.");
  }

  let credentialId = localStorage.getItem(storageKeys.fingerprintCredential);
  if (!credentialId) {
    credentialId = await registerFingerprintCredential();
  }

  const assertion = await navigator.credentials.get({
    publicKey: {
      challenge: randomBytes(32),
      timeout: 60000,
      userVerification: "required",
      allowCredentials: [
        {
          id: base64UrlToBuffer(credentialId),
          type: "public-key"
        }
      ]
    }
  });

  if (!assertion) {
    throw new Error("Fingerprint verification was cancelled.");
  }
}

async function registerFingerprintCredential() {
  const credential = await navigator.credentials.create({
    publicKey: {
      challenge: randomBytes(32),
      rp: { name: "Jarad Mobile" },
      user: {
        id: randomBytes(16),
        name: "jarad-admin",
        displayName: "Jarad Admin"
      },
      pubKeyCredParams: [{ type: "public-key", alg: -7 }, { type: "public-key", alg: -257 }],
      authenticatorSelection: {
        authenticatorAttachment: "platform",
        userVerification: "required"
      },
      timeout: 60000,
      attestation: "none"
    }
  });

  if (!credential) {
    throw new Error("Fingerprint setup was cancelled.");
  }

  const credentialId = bufferToBase64Url(credential.rawId);
  localStorage.setItem(storageKeys.fingerprintCredential, credentialId);
  return credentialId;
}

function randomBytes(length) {
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  return bytes;
}

function bufferToBase64Url(buffer) {
  return btoa(String.fromCharCode(...new Uint8Array(buffer)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

function base64UrlToBuffer(value) {
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, "=");
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}


