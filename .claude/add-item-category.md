# Skill: Add a new item category

You execute this skill when the human asks you to add a new inventory category beyond wine, Halloween, and other — e.g., books, comics, trading cards, vinyl records.

Before you start, the human should have provided in the PR description:

1. The full field list for the category, with types
2. Which fields are AI-extractable from a photo vs. user-only
3. The category's known failure mode (every category has one — e.g., stylized wine vintages, Funko box numbers, comic grading labels)

If those aren't provided, ask before proceeding.

The architecture is designed for this kind of extension. Adding a category should be a code change, not a schema migration or graph rewrite. If the steps below require changing the `items` table schema or restructuring the graph, stop — re-read `SPEC.md` and surface the conflict.

## Steps

### 1. Pydantic model

In `backend/app/models/items.py`, add a new class inheriting from `BaseItem`:

```python
class BookItem(BaseItem):
    category: Literal["book"] = "book"
    publisher: str | None
    title: str | None
    # ... etc
```

Add it to the discriminated union:

```python
Item = Annotated[
    Union[WineItem, HalloweenItem, OtherItem, BookItem],
    Field(discriminator="category"),
]
```

Every new category-specific field must be `| None`. The extraction node returns null for anything it can't see; the user fills it in.

### 2. Extraction prompt

In `backend/app/graph/prompts/extract.py`, add a new prompt constant for the category:

```python
EXTRACT_BOOK_PROMPT = """You are extracting structured information about a book...

Return null for any field you cannot see on the item. Do not guess.

Known failure modes to avoid:
- [the failure mode the human identified]
..."""
```

The explicit "return null if uncertain" and the known-failure-modes section are required, not optional. They are the difference between a pipeline that works and one that hallucinates confidently.

### 3. Router

Update the `category_router` node in `backend/app/graph/nodes/category_router.py` to include the new category in its output enum and its prompt. The router prompt needs an example of each category and explicit guidance on disambiguating close cases ("a book about wine is still a book, not a wine").

### 4. Extraction node dispatch

In `backend/app/graph/nodes/extract_structured.py`, the node dispatches to the correct prompt + Pydantic class based on `state.category`. Add the new branch:

```python
if state.category == "book":
    return await provider.complete_structured(
        prompt=EXTRACT_BOOK_PROMPT,
        image=state.image,
        schema=BookItem,
    )
```

### 5. Mobile form component

In `mobile/components/forms/`, add a new form component for the category. Pattern-match from `WineForm.tsx` or `HalloweenForm.tsx`. The form:

- Receives the prefilled `BookItem` as props
- Renders each field with low-confidence highlighting (check `confidence_scores[field_name]`)
- Lets the user edit
- Submits via the shared `POST /items` call

The form router component (`components/forms/FormRouter.tsx`) dispatches on `category` to pick the right form. Add a branch there.

### 6. Update CLAUDE.md's failure-mode log

Add the category's known failure mode (provided by the human in the PR description) to CLAUDE.md's "Known gotchas" section. Do not edit the "What's explicitly out of scope" list — that's a scope decision the human handles.

## Verification before merging

- [ ] A unit test for the extraction node with a fixture image for the new category passes
- [ ] The category router correctly routes test fixtures to the new category
- [ ] The full graph end-to-end test has a fixture for the new category
- [ ] The mobile form renders the new category's fields without TypeScript errors
- [ ] At least 3 eval fixtures with ground truth exist for the new category. The human provides these; you do not photograph items. See .claude/add-eval-case.md for fixture processing the agent does help with.
- [ ] CLAUDE.md's "Known gotchas" section includes the new category's failure mode

## What NOT to do

- **Do not add a new DB table.** The `items` table handles all categories via the JSONB `details` column. A new table is a design smell — re-read SPEC.md's schema section.
- **Do not add a new graph structure for the category.** The existing graph handles all categories via dispatch in the extraction node.
- **Do not edit the "What's explicitly out of scope" list in CLAUDE.md.** Scope changes are human decisions.
- **Do not proceed without eval fixtures.** A category without ground-truth fixtures is a category that will silently regress on future changes. If the human hasn't provided fixtures, ask before merging.
- **Do not photograph items or generate ground truth.** That's human work. You process fixtures the human provides; you don't create them.