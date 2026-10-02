// Moldura das telas públicas de acesso (recuperar e redefinir senha): logo da
// Precatur sobre o cartão, no mesmo tom da tela de login.
export function AuthMoldura({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-secondary/40 px-4 py-10">
      <div className="w-full max-w-md space-y-6">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/precatur-logo.png" alt="Precatur" className="mx-auto h-11 w-auto object-contain" />
        <div className="rounded-lg border bg-card p-6 shadow-sm sm:p-8">{children}</div>
      </div>
    </main>
  );
}
