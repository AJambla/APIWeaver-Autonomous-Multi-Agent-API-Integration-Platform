import Link from "next/link";
import { Button } from "@/components/Button";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-8 text-center">
      <p className="text-5xl font-bold text-brand-primary">404</p>
      <h1 className="text-xl font-semibold">This project doesn&apos;t exist</h1>
      <p className="max-w-sm text-sm text-text-secondary">
        The project you&apos;re looking for may have been archived, or you don&apos;t have
        access to it.
      </p>
      <Link href="/dashboard">
        <Button>Back to Dashboard</Button>
      </Link>
    </div>
  );
}
