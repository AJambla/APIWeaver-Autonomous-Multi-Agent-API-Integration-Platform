import { AppShell } from "@/components/AppShell";

export default function ProjectLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { id: string };
}) {
  return <AppShell projectId={params.id}>{children}</AppShell>;
}
