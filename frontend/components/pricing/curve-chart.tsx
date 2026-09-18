"use client";

import { useEffect, useRef } from "react";
import { Download } from "lucide-react";
import type { PricingRow } from "@/lib/api";
import { QUARTERS, formatPct } from "@/lib/pricing";
import { Button } from "@/components/ui/button";

// Curva de preço por trimestre. Desenho portado 1:1 do canvas da calculadora
// antiga, para o PNG baixado sair idêntico ao que o time já envia.
const W = 1100;
const H = 410;

export function CurveChart({
  entityLabel,
  row,
  quarter,
}: {
  entityLabel: string;
  row: PricingRow;
  quarter: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const pad = { top: 55, right: 55, bottom: 70, left: 75 };
    const cw = W - pad.left - pad.right;
    const ch = H - pad.top - pad.bottom;

    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, W, H);

    ctx.textAlign = "left";
    ctx.fillStyle = "#073661";
    ctx.font = "bold 22px Arial";
    ctx.fillText(`${entityLabel} — ${row.year}`, pad.left, 31);
    ctx.fillStyle = "#65758b";
    ctx.font = "14px Arial";
    ctx.fillText("Preço máximo de compra por trimestre", pad.left, 51);

    ctx.strokeStyle = "#dce5f0";
    ctx.lineWidth = 1;
    for (let v = 0; v <= 100; v += 20) {
      const y = pad.top + ch - (v / 100) * ch;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(W - pad.right, y);
      ctx.stroke();
      ctx.fillStyle = "#65758b";
      ctx.font = "12px Arial";
      ctx.textAlign = "right";
      ctx.fillText(`${v}%`, pad.left - 12, y + 4);
    }

    const pts = row.values.map((value, i) => ({
      x: pad.left + (i * cw) / (row.values.length - 1),
      y: pad.top + ch - (value / 100) * ch,
      value,
    }));

    ctx.beginPath();
    pts.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
    ctx.strokeStyle = "#0d4d8d";
    ctx.lineWidth = 5;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.stroke();

    pts.forEach((p, i) => {
      const sel = i === quarter;
      ctx.beginPath();
      ctx.arc(p.x, p.y, sel ? 10 : 7, 0, Math.PI * 2);
      ctx.fillStyle = sel ? "#057a55" : "#0d4d8d";
      ctx.fill();
      ctx.beginPath();
      ctx.arc(p.x, p.y, sel ? 4 : 3, 0, Math.PI * 2);
      ctx.fillStyle = "#ffffff";
      ctx.fill();

      ctx.textAlign = "center";
      ctx.fillStyle = sel ? "#057a55" : "#073661";
      ctx.font = "bold 16px Arial";
      ctx.fillText(formatPct(p.value), p.x, p.y - 18);
      ctx.fillStyle = "#53657b";
      ctx.font = "bold 13px Arial";
      ctx.fillText(QUARTERS[i], p.x, H - 32);
    });
    ctx.textAlign = "left";
  }, [entityLabel, row, quarter]);

  function download() {
    const canvas = ref.current;
    if (!canvas) return;
    const slug = `${entityLabel}-${row.year}`
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/[^a-zA-Z0-9]+/g, "-")
      .toLowerCase();
    const a = document.createElement("a");
    a.download = `precificacao-${slug}.png`;
    a.href = canvas.toDataURL("image/png");
    a.click();
  }

  return (
    <div className="space-y-3">
      <canvas ref={ref} width={W} height={H} className="h-auto w-full rounded-md border" />
      <div className="flex justify-end">
        <Button variant="outline" size="sm" className="gap-2" onClick={download}>
          <Download className="h-4 w-4" />
          Baixar gráfico em PNG
        </Button>
      </div>
    </div>
  );
}
