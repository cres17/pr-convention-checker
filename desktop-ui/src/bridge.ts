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
export interface Bridge {
  initialize: () => void;
  chooseRepository: () => void;
  startScan: (path: string, base: string) => void;
  previewReview: () => void;
  startReview: (provider: string, path: string) => void;
  cancelReview: () => void;
  exportReport: (kind: string) => void;
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
