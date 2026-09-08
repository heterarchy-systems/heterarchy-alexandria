"use strict";

const elements = {
  coreDot: document.querySelector("#core-dot"),
  coreStatus: document.querySelector("#core-status"),
  semanticDot: document.querySelector("#semantic-dot"),
  semanticStatus: document.querySelector("#semantic-status"),
  mcpEndpoint: document.querySelector("#mcp-endpoint"),
  mcpMode: document.querySelector("#mcp-mode"),
  mcpIssuer: document.querySelector("#mcp-issuer"),
  mcpNotice: document.querySelector("#mcp-notice"),
  copyMcpEndpoint: document.querySelector("#copy-mcp-endpoint"),
  generatePairingCode: document.querySelector("#generate-pairing-code"),
  pairingPanel: document.querySelector("#pairing-panel"),
  pairingCode: document.querySelector("#pairing-code"),
  pairingExpiry: document.querySelector("#pairing-expiry"),
  mcpMessage: document.querySelector("#mcp-message"),
};

function setDot(dot, tone) {
  dot.className = `status-dot ${tone}`;
}

function setMessage(element, text, isError = false) {
  element.textContent = text;
  element.className = isError ? "message error" : "message";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail || payload.message || detail;
    } catch {
      // Preserve the HTTP status when the response is not JSON.
    }
    throw new Error(detail);
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

async function loadReadiness() {
  try {
    const readiness = await api("/operations/readiness");
    const coreHealthy = readiness.database.reachable
      && readiness.vault.exists
      && readiness.vault.readable
      && readiness.rag.fts === "HEALTHY";
    elements.coreStatus.textContent = coreHealthy ? "사용 가능" : "점검 필요";
    setDot(elements.coreDot, coreHealthy ? "ok" : "error");

    const semanticHealthy = readiness.rag.effective_strategy === "HYBRID"
      && readiness.rag.embedding === "HEALTHY"
      && readiness.rag.vector === "HEALTHY";
    elements.semanticStatus.textContent = semanticHealthy
      ? "Hybrid 준비"
      : `${readiness.rag.effective_strategy} · 복구 필요`;
    setDot(elements.semanticDot, semanticHealthy ? "ok" : "warn");
  } catch {
    elements.coreStatus.textContent = "상태 조회 실패";
    elements.semanticStatus.textContent = "상태 조회 실패";
    setDot(elements.coreDot, "error");
    setDot(elements.semanticDot, "error");
  }
}

async function loadMcpStatus() {
  try {
    const status = await api("/connect/status");
    elements.mcpEndpoint.textContent = status.mcp_endpoint;
    elements.mcpMode.textContent = status.mcp_auth_mode;
    elements.mcpIssuer.textContent = status.mcp_oauth_issuer || "—";
    if (status.mcp_oauth_enabled) {
      elements.mcpNotice.textContent = "MCP OAuth가 활성화되어 있습니다. 클라이언트에 Endpoint를 등록하면 브라우저 승인 화면이 열립니다.";
      elements.mcpNotice.className = "notice ok";
      elements.generatePairingCode.hidden = false;
    } else {
      elements.mcpNotice.textContent = "현재 MCP 인증이 비활성화되어 있습니다. local_oauth2 모드에서 안전하게 연결할 수 있습니다.";
      elements.mcpNotice.className = "notice warn";
    }
    if (!status.local_only) {
      elements.mcpNotice.textContent += " 이 페이지는 로컬호스트 밖에서 열렸습니다. 공개 배포에는 HTTPS와 운영자 인증이 필요합니다.";
      elements.mcpNotice.className = "notice warn";
    }
  } catch (error) {
    elements.mcpNotice.textContent = "MCP 상태를 불러오지 못했습니다.";
    elements.mcpNotice.className = "notice warn";
    setMessage(elements.mcpMessage, error.message, true);
  }
}

async function copyMcpEndpoint() {
  try {
    await navigator.clipboard.writeText(elements.mcpEndpoint.textContent);
    setMessage(elements.mcpMessage, "MCP Endpoint를 복사했습니다.");
  } catch {
    setMessage(elements.mcpMessage, "클립보드 복사에 실패했습니다.", true);
  }
}

async function generatePairingCode() {
  elements.generatePairingCode.disabled = true;
  try {
    const pairing = await api("/connect/mcp/pairing-code", { method: "POST" });
    elements.pairingCode.textContent = pairing.code;
    elements.pairingExpiry.textContent = `만료: ${pairing.expires_at}`;
    elements.pairingPanel.hidden = false;
    let copied = true;
    try {
      await navigator.clipboard.writeText(pairing.code);
    } catch {
      copied = false;
    }
    setMessage(
      elements.mcpMessage,
      copied
        ? "일회용 코드를 생성하고 클립보드에 복사했습니다. MCP 승인 페이지에 입력하세요."
        : "일회용 코드를 생성했습니다. MCP 승인 페이지에 직접 입력하세요.",
    );
  } catch (error) {
    setMessage(elements.mcpMessage, error.message, true);
  } finally {
    elements.generatePairingCode.disabled = false;
  }
}

elements.copyMcpEndpoint.addEventListener("click", copyMcpEndpoint);
elements.generatePairingCode.addEventListener("click", generatePairingCode);

Promise.all([loadReadiness(), loadMcpStatus()]);
