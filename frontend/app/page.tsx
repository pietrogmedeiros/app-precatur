import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { landingFor } from "@/lib/auth";

export default function Home() {
  // O perfil vem do cookie porque a home é renderizada no servidor.
  redirect(landingFor(cookies().get("role")?.value));
}
