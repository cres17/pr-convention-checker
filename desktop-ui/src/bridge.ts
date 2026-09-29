export type Group = { name: string; required?: string[]; evidence?: string };
export type Decision = {
  rule_id: string;
  status: string;
  reason: string;
  severity?: string;
  trigger_files: string[];
  unsatisfied_groups: Group[];
  satisfied_groups: Group[];
};
export type Violation = {
  rule_id: string;
  severity: string;
  confidence: string;
  message: string;
  checklist: string[];
  missing_docs_explanation: string;
  changed_contract_summary: string;
  docs_update_draft: string;
  false_positive_note: string;
};
export type PolicyPreview = {
  repository: string;
  exists: boolean;
  preset: string;
  presets: string[];
  recommendations: { presets: string[]; frameworks: string[]; docs_paths: string[] };
  policy: string;
};
export type ScanImpact = {
  scan_at: string;
  version: number;
  items: { id: string; title: string; path: string; line?: number; change: string; invalidated: boolean }[];
  documents: { path: string; invalidated: boolean }[];
};
export type Scan = {
  repository: string;
  base: string;
  at: string;
  changed_file_count: number;
  policy: string;
  files: { path: string; patch: string; status: string }[];
  result: {
    result: string;
    rule_decisions: Decision[];
    violations?: Violation[];
    [key: string]: unknown;
  };
};
export type Review = {
  provider: string;
  verdict: string;
  summary: string;
  findings: { rule_id: string; reason: string; suggestion: string }[];
  limitations: string[];
};
export type ProgressItem = {
  id: string;
  title: string;
  criterion: string;
  area: string;
  included: boolean;
  source: { path: string; line: number; excerpt: string; sha256: string };
  implementation_status: "unknown" | "partial" | "implemented" | "not_implemented";
  implementation_note?: string;
  evidence: { path: string; line: number; excerpt?: string; sha256?: string; note: string } | null;
  verification_status: "unverified" | "verified";
  verification_note: string;
  stale_evidence?: boolean;
  doc_marked_done?: boolean;
  doc_claim?: "unbacked" | null;
  duplicates?: { path: string; line: number; excerpt: string; criterion: string }[];
  effective_status?: ProgressItem["implementation_status"] | "excluded";
};
export type ProgressFieldError = { id: string; field: string; message: string };
export type ChangeCounts = Partial<Record<"gained" | "regressed" | "excluded" | "reincluded" | "added" | "removed", number>>;
export type ProgressHistory = {
  snapshots: {
    at: string;
    version: number;
    head: string;
    total: number;
    counts: Record<string, number>;
    changes?: ChangeCounts;
    complete_delta?: number;
  }[];
  since_save: null | ({
    since: string;
    version: number;
    complete_delta: number;
    counts: ChangeCounts;
  } & Record<"gained" | "regressed" | "excluded" | "reincluded" | "added" | "removed", { id: string; title: string }[]>);
};
export type LinkIssue = {
  path: string;
  line: number;
  target: string;
  kind: "link" | "path" | "document";
  confidence?: "high" | "low";
  message: string;
};
export type LinkReport = {
  documents: string[];
  checked: number;
  issues: LinkIssue[];
  truncated: boolean;
  limitations: string;
};
export type ProgressBaseline = {
  repository: string;
  documents: Record<string, string>;
  requirements: ProgressItem[];
  version?: number;
};
export type ProgressReport = {
  repository: string;
  version: number;
  at: string;
  head: string;
  stale_documents: string[];
  total: number;
  counts: Record<string, number>;
  items: ProgressItem[];
  doc_claims_unbacked?: number;
  limitations: string;
};
export interface Bridge {
  initialize: () => void;
  chooseRepository: () => void;
  startScan: (path: string, base: string) => void;
  previewReview: () => void;
  startReview: (provider: string, path: string) => void;
  cancelReview: () => void;
  exportReport: (kind: string) => void;
  previewPolicy: (path: string, preset: string) => void;
  createPolicy: (path: string, preset: string) => void;
  checkProgressLinks: (path: string) => void;
  exportProgress: (path: string, kind: string) => void;
  openDocument: (relative: string) => void;
  listProjectDocs: (path: string) => void;
  previewProgress: (path: string, selectedJson: string) => void;
  saveProgress: (path: string, payloadJson: string) => void;
  inspectProgress: (path: string) => void;
  suggestProgressEvidence: (path: string, itemJson: string) => void;
  event: { connect: (fn: (message: string) => void) => void };
}
declare global {
  interface Window {
    qt?: { webChannelTransport: unknown };
    QWebChannel?: new (
      transport: unknown,
      callback: (channel: { objects: { desktop: Bridge } }) => void,
    ) => void;
  }
}
export function connect(onEvent: (event: any) => void): Promise<Bridge | null> {
  if (!window.qt) return Promise.resolve(null);
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "qrc:///qtwebchannel/qwebchannel.js";
    script.onerror = () =>
      reject(new Error("데스크톱 연결을 불러오지 못했습니다."));
    script.onload = () =>
      new window.QWebChannel!(window.qt!.webChannelTransport, (channel) => {
        const bridge = channel.objects.desktop;
        bridge.event.connect((raw) => {
          try {
            onEvent(JSON.parse(raw));
          } catch {
            onEvent({ type: "error", message: "앱 응답을 읽지 못했습니다." });
          }
        });
        resolve(bridge);
        bridge.initialize();
      });
    document.head.append(script);
  });
}
