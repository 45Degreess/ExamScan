import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.jsx";

function response(status, body) {
  return new Response(body == null ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const adminUser = {
  id: 1,
  uct_id: "TSTADM001",
  name: "Test Admin",
  email: "admin@example.test",
  role: "admin",
  active: true,
};

function installFetch({ authenticatedUser = null, sessionsStatus = 200, staff = [] } = {}) {
  const mock = vi.fn(async (input, options = {}) => {
    const url = String(input);
    const method = (options.method || "GET").toUpperCase();
    if (url.endsWith("/api/auth/me")) {
      return authenticatedUser
        ? response(200, { user: authenticatedUser, csrf_token: "csrf-token" })
        : response(401, { detail: "Authentication required." });
    }
    if (url.endsWith("/api/health")) return response(200, { ok: true });
    if (url.endsWith("/api/pi/health")) return response(200, { ok: true });
    if (url.endsWith("/api/sessions")) {
      return sessionsStatus === 200
        ? response(200, { sessions: [] })
        : response(sessionsStatus, { detail: "Authentication required." });
    }
    if (url.endsWith("/api/auth/logout") && method === "POST") {
      return response(200, { message: "Signed out." });
    }
    if (url.endsWith("/api/admin/users") && method === "GET") {
      return response(200, staff);
    }
    if (url.endsWith("/api/admin/users") && method === "POST") {
      const payload = JSON.parse(options.body);
      return response(201, {
        user: { id: 2, ...payload, active: true },
        password_email_sent: true,
      });
    }
    if (/\/api\/admin\/users\/\d+$/.test(url) && method === "PATCH") {
      return response(200, { ...staff[0], ...JSON.parse(options.body) });
    }
    if (/\/api\/admin\/users\/\d+\/password$/.test(url) && method === "POST") {
      return response(202, { message: "A new password has been emailed." });
    }
    if (url.endsWith("/api/auth/password/request")) {
      return response(202, { message: "If that UCT ID is registered and eligible, a password email will be sent shortly." });
    }
    if (url.endsWith("/api/auth/login") && method === "POST") {
      return response(200, {
        user: adminUser,
        csrf_token: "csrf-token",
      });
    }
    return response(404, { detail: `Unhandled test request: ${method} ${url}` });
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("ExamScan authentication routes", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/login");
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("emails a password without submitting a blank login", async () => {
    installFetch();
    render(<App />);
    await screen.findByRole("heading", { name: "Staff sign in" });
    fireEvent.change(screen.getByLabelText("UCT ID"), { target: { value: "tstadm001" } });
    const emailButton = screen.getByRole("button", { name: "Email me a password" });
    await waitFor(() => expect(emailButton).toBeEnabled());
    fireEvent.click(emailButton);
    expect(await screen.findByRole("status")).toHaveTextContent("password email will be sent");
  });

  it("signs in and opens the protected dashboard", async () => {
    installFetch();
    render(<App />);
    await screen.findByRole("heading", { name: "Staff sign in" });
    fireEvent.change(screen.getByLabelText("UCT ID"), { target: { value: "tstadm001" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "generated-password" } });
    const signInButton = screen.getByRole("button", { name: "Sign in" });
    await waitFor(() => expect(signInButton).toBeEnabled());
    fireEvent.click(signInButton);
    expect(await screen.findByRole("heading", { name: "ExamScan dashboard" })).toBeInTheDocument();
  });

  it("redirects an anonymous protected route to login", async () => {
    window.history.replaceState({}, "", "/sessions/new");
    installFetch();
    render(<App />);
    await waitFor(() => expect(window.location.pathname).toBe("/login"));
  });

  it("does not expose staff administration to operators", async () => {
    window.history.replaceState({}, "", "/admin/users");
    installFetch({
      authenticatedUser: { id: 2, uct_id: "TSTOPR001", name: "Test Operator", email: "operator@example.test", role: "operator", active: true },
    });
    render(<App />);
    await waitFor(() => expect(window.location.pathname).toBe("/"));
    expect(await screen.findByRole("heading", { name: "ExamScan dashboard" })).toBeInTheDocument();
  });

  it("restores an administrator session and exposes staff navigation", async () => {
    window.history.replaceState({}, "", "/");
    installFetch({ authenticatedUser: adminUser });
    render(<App />);
    const staffButton = await screen.findByRole("button", { name: "Staff" });
    fireEvent.click(staffButton);
    expect(await screen.findByRole("heading", { name: "Staff accounts" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/admin/users");
  });

  it("logs out, sends CSRF, and returns to login", async () => {
    window.history.replaceState({}, "", "/");
    const fetchMock = installFetch({ authenticatedUser: adminUser });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(window.location.pathname).toBe("/login"));
    const logoutCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/api/auth/logout"));
    expect(logoutCall).toBeTruthy();
    expect(new Headers(logoutCall[1].headers).get("X-CSRF-Token")).toBe("csrf-token");
  });

  it("returns to login when a protected request receives 401", async () => {
    window.history.replaceState({}, "", "/");
    installFetch({ authenticatedUser: adminUser, sessionsStatus: 401 });
    render(<App />);
    await waitFor(() => expect(window.location.pathname).toBe("/login"));
    expect(await screen.findByRole("heading", { name: "Staff sign in" })).toBeInTheDocument();
  });

  it("lets an administrator create a staff account", async () => {
    window.history.replaceState({}, "", "/admin/users");
    const fetchMock = installFetch({ authenticatedUser: adminUser });
    render(<App />);
    await screen.findByRole("heading", { name: "Staff accounts" });
    fireEvent.change(screen.getByLabelText("UCT ID"), { target: { value: "tstopr001" } });
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Test Operator" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "operator@example.test" } });
    fireEvent.click(screen.getByRole("button", { name: "Add and email password" }));
    expect(await screen.findByRole("status")).toHaveTextContent("password emailed");
    const createCall = fetchMock.mock.calls.find(
      ([url, options]) => String(url).endsWith("/api/admin/users") && options.method === "POST",
    );
    expect(JSON.parse(createCall[1].body).uct_id).toBe("TSTOPR001");
  });

  it("lets an administrator edit, deactivate, and resend a staff password", async () => {
    window.history.replaceState({}, "", "/admin/users");
    const operator = {
      id: 2,
      uct_id: "TSTOPR001",
      name: "Test Operator",
      email: "operator@example.test",
      role: "operator",
      active: true,
    };
    const fetchMock = installFetch({ authenticatedUser: adminUser, staff: [operator] });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.click(screen.getByLabelText("Active account"));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByText("Staff account updated.");

    const updateCall = fetchMock.mock.calls.find(
      ([url, options]) => /\/api\/admin\/users\/2$/.test(String(url)) && options.method === "PATCH",
    );
    expect(JSON.parse(updateCall[1].body).active).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Send password" }));
    expect(await screen.findByRole("status")).toHaveTextContent("new password has been emailed");
    expect(fetchMock.mock.calls.some(
      ([url, options]) => String(url).endsWith("/api/admin/users/2/password") && options.method === "POST",
    )).toBe(true);
  });
});
