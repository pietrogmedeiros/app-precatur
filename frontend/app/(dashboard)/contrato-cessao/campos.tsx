import {
  formatarMoeda,
  reaisPorExtenso,
} from "@/lib/contrato-cessao";

/** Valor digitado, ou uma linha para preencher à mão (igual ao termo de vista). */
export function V({ v, w = 14 }: { v: string; w?: number }) {
  const t = v.trim();
  return t ? (
    <>{t}</>
  ) : (
    <span className="contrato-linha" style={{ width: `${w}em` }} />
  );
}

/** "R$ 285.045,82" ou linha. */
export function Din({ n }: { n: number | null }) {
  return n === null ? (
    <span className="contrato-linha" style={{ width: "9em" }} />
  ) : (
    <>R$ {formatarMoeda(n)}</>
  );
}

/** Valor por extenso ou linha. */
export function Ext({ n }: { n: number | null }) {
  return n === null ? (
    <span className="contrato-linha" style={{ width: "20em" }} />
  ) : (
    <>{reaisPorExtenso(n)}</>
  );
}

/** "100% (cem por cento)" ou linha. */
export function Pct({ t }: { t: string | null }) {
  return t ? <>{t}</> : <span className="contrato-linha" style={{ width: "8em" }} />;
}
