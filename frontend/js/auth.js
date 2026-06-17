export async function registerPasskey(api) {
  assertWebAuthnAvailable();
  const deviceLabel = defaultDeviceLabel();
  const { challengeId, options } = await api.getPasskeyRegistrationOptions(deviceLabel);
  const credential = await navigator.credentials.create({
    publicKey: decodeCreationOptions(options)
  });
  if (!credential) {
    throw new Error("Passkey setup was cancelled.");
  }
  return api.verifyPasskeyRegistration(challengeId, publicKeyCredentialToJSON(credential), deviceLabel);
}

export async function verifyPasskeyForAction(api, action) {
  assertWebAuthnAvailable();
  const { challengeId, options } = await api.getPasskeyAuthenticationOptions(action);
  const assertion = await navigator.credentials.get({
    publicKey: decodeRequestOptions(options)
  });
  if (!assertion) {
    throw new Error("Passkey verification was cancelled.");
  }
  return api.verifyPasskeyAuthentication(challengeId, publicKeyCredentialToJSON(assertion), action);
}

function assertWebAuthnAvailable() {
  if (!window.isSecureContext) {
    throw new Error("Passkeys require HTTPS or localhost.");
  }
  if (!window.PublicKeyCredential || !navigator.credentials) {
    throw new Error("Passkeys are not available in this browser.");
  }
}

function defaultDeviceLabel() {
  const platform = navigator.userAgentData?.platform || navigator.platform || "This device";
  return `${platform} passkey`;
}

function decodeCreationOptions(options) {
  return {
    ...options,
    challenge: base64UrlToBuffer(options.challenge),
    user: {
      ...options.user,
      id: base64UrlToBuffer(options.user.id)
    },
    excludeCredentials: (options.excludeCredentials || []).map(decodeCredentialDescriptor)
  };
}

function decodeRequestOptions(options) {
  return {
    ...options,
    challenge: base64UrlToBuffer(options.challenge),
    allowCredentials: (options.allowCredentials || []).map(decodeCredentialDescriptor)
  };
}

function decodeCredentialDescriptor(credential) {
  return {
    ...credential,
    id: base64UrlToBuffer(credential.id)
  };
}

function publicKeyCredentialToJSON(credential) {
  const response = {};
  for (const key of ["clientDataJSON", "attestationObject", "authenticatorData", "signature", "userHandle"]) {
    const value = credential.response[key];
    if (value instanceof ArrayBuffer) {
      response[key] = bufferToBase64Url(value);
    } else if (value !== undefined && value !== null) {
      response[key] = value;
    }
  }
  if (typeof credential.response.getTransports === "function") {
    response.transports = credential.response.getTransports();
  }

  const json = {
    id: credential.id,
    rawId: bufferToBase64Url(credential.rawId),
    type: credential.type,
    response
  };

  if (credential.authenticatorAttachment) {
    json.authenticatorAttachment = credential.authenticatorAttachment;
  }
  if (typeof credential.getClientExtensionResults === "function") {
    json.clientExtensionResults = credential.getClientExtensionResults();
  }
  return json;
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
