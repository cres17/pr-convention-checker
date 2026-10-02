import { lazy, Suspense } from "react";
import type { Scan } from "../../bridge";
const CodeDiff = lazy(() => import("../../components/tool-ui/code-diff").then((module) => ({ default: module.CodeDiff })));
/** Load the rich diff renderer only when there is a patch; keep a readable fallback. */
export default function ReviewDiff({ file }: {
    file: Scan["files"][number];
}) {
    const patch = file.patch.startsWith("diff --git ") ? file.patch
        : `diff --git a/${file.path} b/${file.path}\n--- a/${file.path}\n+++ b/${file.path}\n${file.patch}`;
    return <Suspense fallback={<pre aria-label="코드 변경 내용">{patch}</pre>}>
    <CodeDiff id="file-diff" patch={patch} filename={file.path} language="text" lineNumbers="visible" diffStyle="unified" maxCollapsedLines={14}/>
  </Suspense>;
}
