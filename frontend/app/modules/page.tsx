import { redirect } from "next/navigation";

/**
 * The switches moved to /main-control, which controls every module in the app rather than
 * only the auto-trading desks, and gates the API as well as the schedulers.
 *
 * This stays as a redirect rather than being deleted: the sidebar entry, bookmarks and the
 * links inside the older notices all point at /modules, and two pages writing the same
 * switches is how you end up looking at a stale one and believing it.
 */
export default function ModulesPage() {
  redirect("/main-control");
}
