import { NextResponse } from "next/server";
import { backendFetch } from "@/lib/backend";

export async function GET() {
  const response = await backendFetch("/health");
  const body = await response.json();

  return NextResponse.json(body, {
    status: response.status,
  });
}
