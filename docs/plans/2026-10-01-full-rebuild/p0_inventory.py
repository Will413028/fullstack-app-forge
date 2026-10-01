"""Extract structural interfaces from the pinned reference without reading configuration."""

import argparse
import json
from pathlib import Path
import re
import subprocess

PIN = "893918c808ce7828cd4b9372967e064ed119bbaa"


def extract(root):
    revision = subprocess.check_output(["/usr/bin/git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if revision != PIN:
        raise ValueError("reference revision does not match pinned inventory")
    paths = subprocess.check_output(["/usr/bin/git", "-C", str(root), "ls-files"], text=True).splitlines()
    controllers = []
    entities = []
    tools = []
    for relative in paths:
        path = Path(relative)
        if path.suffix != ".java" or "/src/main/" not in "/" + relative:
            continue
        if "/controller/" not in relative and "/model/entity/" not in relative and "/tools/" not in relative:
            continue
        text = (root / path).read_text()
        variant = "microservice" if relative.startswith("yu-ai-code-mother-microservice/") else "monolith"
        if "/controller/" in relative:
            base_match = re.search(r'@RequestMapping\("([^"\n]*)"\)', text)
            base = base_match.group(1) if base_match else ""
            for match in re.finditer(r'@(Get|Post|Put|Delete|Patch)Mapping(?:\((.*?)\))?', text, re.S):
                quoted = re.search(r'"([^"\n]*)"', match.group(2) or "")
                suffix = quoted.group(1) if quoted else ""
                tail = text[match.end():]
                method = re.search(r'public\s+[\w<>, ?\[\].]+\s+(\w+)\s*\(', tail)
                owner = path.stem
                rid = {"UserController": "R01", "AppController": "R02",
                       "ChatHistoryController": "R05", "StaticResourceController": "R09",
                       "HealthController": "R09", "WorkflowSseController": "R03"}.get(owner)
                if not rid or not method:
                    raise ValueError("unmapped controller interface: " + relative)
                symbol = method.group(1)
                if owner == "AppController":
                    rid = ("R04" if symbol == "chatToGenCode" else "R10" if symbol == "deployApp"
                           else "R12" if symbol == "downloadAppCode" else "R13"
                           if "Admin" in symbol or symbol == "listGoodAppVOByPage" else "R02")
                if owner == "ChatHistoryController" and "Admin" in symbol:
                    rid = "R13"
                controllers.append({"variant": variant, "method": match.group(1).upper(),
                                    "path": base + suffix, "symbol": symbol,
                                    "source": relative, "line": text.count("\n", 0, match.start()) + 1,
                                    "requirement": rid, "disposition": "rewrite-as-fastapi-contract"})
        elif "/model/entity/" in relative:
            table = re.search(r'@Table\("([^"\n]*)"\)', text)
            entities.append({"variant": variant, "name": path.stem,
                             "table": table.group(1) if table else "unmapped",
                             "fields": [{"type": m.group(1), "name": m.group(2)} for m in
                                        re.finditer(r'private\s+(\w+(?:<[^>]+>)?)\s+(\w+)\s*;', text)],
                             "source": relative,
                             "requirement": {"User": "R01", "App": "R02", "ChatHistory": "R05"}[path.stem],
                             "disposition": "rewrite-with-platform-schema"})
        elif "/tools/" in relative:
            for match in re.finditer(r'@Tool\([^\n]*\)', text):
                method = re.search(r'public\s+[\w<>, ?\[\].]+\s+(\w+)\s*\(', text[match.end():])
                if not method:
                    raise ValueError("unparsed tool: " + relative)
                rid = "R17" if "/langgraph4j/" in relative else "R04"
                tools.append({"variant": variant, "symbol": method.group(1), "source": relative,
                              "line": text.count("\n", 0, match.start()) + 1, "requirement": rid,
                              "disposition": "rewrite-as-constrained-tool"})
    router_path = "yu-ai-code-mother-frontend/src/router/index.ts"
    router = (root / router_path).read_text()
    routes = [{"path": match.group(1), "source": router_path,
               "line": router.count("\n", 0, match.start()) + 1,
               "requirement": "R01" if "/user/" in match.group(1) else "R13" if "/admin/" in match.group(1)
               else "R06" if "/app/" in match.group(1) else "R02",
               "disposition": "rewrite-as-nextjs-page"}
              for match in re.finditer(r"path:\s*['\"]([^'\"]+)['\"]", router)]
    apis = []
    for relative in paths:
        if not re.fullmatch(r"yu-ai-code-mother-frontend/src/api/\w+Controller\.ts", relative):
            continue
        text = (root / relative).read_text()
        for match in re.finditer(r"export async function (\w+)\s*\(", text):
            rest = text[match.end():]
            endpoint = re.search(r"request<[^\n]+\(\s*['\"`]([^'\"`]+)['\"`]", rest)
            if not endpoint:
                raise ValueError("unparsed API wrapper: " + match.group(1))
            apis.append({"symbol": match.group(1), "path": endpoint.group(1) if endpoint else "unparsed",
                         "source": relative, "line": text.count("\n", 0, match.start()) + 1,
                         "requirement": next(c["requirement"] for c in controllers
                                             if c["symbol"].lower() == match.group(1).lower()),
                         "disposition": "replace-with-generated-openapi-client"})
    consumers = []
    for relative in paths:
        if not relative.startswith("yu-ai-code-mother-frontend/src/") or Path(relative).suffix not in (".vue", ".ts"):
            continue
        if "/api/" in relative:
            continue
        text = (root / relative).read_text()
        for match in re.finditer(r"from\s+['\"]@/api/(\w+Controller)['\"]", text):
            consumers.append({"source": relative, "line": text.count("\n", 0, match.start()) + 1,
                              "interface": match.group(1), "disposition": "replace-with-nextjs-api-consumer"})
        for match in re.finditer(r"new EventSource\(|await fetch\(", text):
            consumers.append({"source": relative, "line": text.count("\n", 0, match.start()) + 1,
                              "interface": "direct-eventsource" if "EventSource" in match.group() else "direct-fetch",
                              "disposition": "replace-with-authorized-run-stream-or-download"})
    return {"revision": revision, "tracked_file_count": len(paths),
            "license_paths": [p for p in paths if re.search(r"(^|/)(license|licence|copying|notice)(\.|$)", p, re.I)],
            "excluded_sources": [".env*", "application*.yml", "config/**", "dotfiles", "connection notes"],
            "controllers": controllers, "entities": entities, "tools": tools, "routes": routes,
            "frontend_api": apis, "consumers": consumers}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = extract(args.reference)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"revision": result["revision"], "tracked_files": result["tracked_file_count"],
                      "controllers": {variant: sum(x["variant"] == variant for x in result["controllers"])
                                      for variant in ("monolith", "microservice")},
                      "routes": len(result["routes"]), "entities": len(result["entities"]),
                      "tools": len(result["tools"]), "frontend_api": len(result["frontend_api"]),
                      "license_paths": result["license_paths"]}))


if __name__ == "__main__":
    main()
