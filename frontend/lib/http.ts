import { ApiError, type Requester } from "./domain";

export async function readJson<T>(response: Response): Promise<T> {
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    const message = typeof detail === "string" ? detail : Array.isArray(detail)
      ? detail.map((item) => `${item.loc?.slice(1).join(" › ") || "Field"}: ${item.msg}`).join(" · ")
      : "This action could not be completed. Try again.";
    throw new ApiError(response.status, message);
  }
  return data as T;
}

export const backendRequest: Requester = async (path, method = "GET", data) => {
  const response = await fetch("/api/resolve" + path, {
    method, cache: "no-store", credentials: "same-origin",
    ...(data !== undefined && { headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) }),
  });
  if (response.status === 401 && typeof window !== "undefined" && window.location.pathname.startsWith("/workspace")) {
    window.location.replace("/login");
  }
  return readJson(response);
};
