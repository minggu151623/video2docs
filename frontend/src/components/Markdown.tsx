import { useMemo } from "react";
import MarkdownIt from "markdown-it";
import DOMPurify from "dompurify";
const parser = new MarkdownIt({ html: false, linkify: false }).enable("table");
const image = parser.renderer.rules.image!;
parser.renderer.rules.image = (tokens, index, options, env, self) => {
  const token = tokens[index];
  const match = /^assets\/([a-f0-9-]{36})\.png$/.exec(
    String(token.attrGet("src") ?? ""),
  );
  if (!match)
    return '<span class="review-label">Ảnh ngoài evidence manifest bị chặn</span>';
  token.attrSet("src", `/api/v1/evidence/${match[1]}/image`);
  return image(tokens, index, options, env, self);
};
const link =
  parser.renderer.rules.link_open ??
  ((tokens, index, options, _env, self) =>
    self.renderToken(tokens, index, options));
parser.renderer.rules.link_open = (tokens, index, options, env, self) => {
  const href = String(tokens[index].attrGet("href") ?? "");
  if (!/^#t=\d+(\.\d+)?$/.test(href)) tokens[index].attrs = [];
  return link(tokens, index, options, env, self);
};
export default function Markdown({
  text,
  onSeek,
  onImage,
}: {
  text: string;
  onSeek: (s: number) => void;
  onImage: (src: string) => void;
}) {
  const html = useMemo(
    () =>
      DOMPurify.sanitize(parser.render(text), {
        FORBID_TAGS: ["script", "iframe", "style", "form"],
        FORBID_ATTR: ["style"],
      }),
    [text],
  );
  return (
    <article
      className="prose"
      onClick={(e) => {
        const el = e.target as HTMLElement;
        if (el.tagName === "A") {
          const match = /^#t=([\d.]+)$/.exec(el.getAttribute("href") ?? "");
          if (match) {
            e.preventDefault();
            onSeek(Number(match[1]));
          }
        }
        if (el.tagName === "IMG") onImage((el as HTMLImageElement).src);
      }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
