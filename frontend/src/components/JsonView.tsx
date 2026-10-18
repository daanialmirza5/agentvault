import clsx from "clsx";

export function JsonView({ value, className, maxHeight = "20rem", label }: {
  value: unknown;
  className?: string;
  maxHeight?: string;
  label?: string;
}) {
  const text = JSON.stringify(value, null, 2) ?? "undefined";
  return (
    <pre
      aria-label={label}
      tabIndex={0}
      style={{ maxHeight }}
      className={clsx(
        "overflow-auto rounded-md border border-slate-200 bg-slate-50 p-3 font-mono text-[11px] leading-relaxed text-slate-700",
        className,
      )}
    >
      {text}
    </pre>
  );
}
