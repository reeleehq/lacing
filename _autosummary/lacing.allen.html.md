# lacing.allen

Allen’s 13 interval relations as pure predicates.

Public predicate API — never write ad-hoc overlap checks elsewhere in lacing.
See ANN-DOC §A and `.claude/skills/lacing-time-and-intervals/SKILL.md`.

Convention: intervals are half-open `[start, end)`. Boundary cases for
`meets`/`met_by` use exact equality on rational time. Half-open
intervals share zero measure at a boundary, so `meets` is NOT an
intersection — see [`intersects()`](#lacing.allen.intersects).

Relation table (a R b means: a’s relation to b is R):

| Relation      | Sym.   | Predicate (with intervals a, b)       |
|---------------|--------|---------------------------------------|
| before        | <      | a.end < b.start                       |
| after         | >      | a.start > b.end                       |
| meets         | m      | a.end == b.start                      |
| met_by        | mi     | a.start == b.end                      |
| overlaps      | o      | a.start < b.start < a.end < b.end     |
| overlapped_by | oi     | b.start < a.start < b.end < a.end     |
| starts        | s      | a.start == b.start and a.end < b.end  |
| started_by    | si     | a.start == b.start and a.end > b.end  |
| during        | d      | a.start > b.start and a.end < b.end   |
| contains      | di     | a.start < b.start and a.end > b.end   |
| finishes      | f      | a.start > b.start and a.end == b.end  |
| finished_by   | fi     | a.start < b.start and a.end == b.end  |
| equals        | =      | a.start == b.start and a.end == b.end |

### Module Attributes

| [`PREDICATE_BY_RELATION`](#lacing.allen.PREDICATE_BY_RELATION)   | Lookup table — used by `IntervalAnnotationStore` to dispatch by relation.   |
|--------------------------------------------------------------------------|-----------------------------------------------------------------------------|

### Functions

| [`after`](#lacing.allen.after)(a, b)         | Allen relation `after`: true when `a` after `b`.                    |
|----------------------------------------------------------------------|---------------------------------------------------------------------|
| [`before`](#lacing.allen.before)(a, b)        | Allen relation `before`: true when `a` before `b`.                  |
| [`compose`](#lacing.allen.compose)(r1, r2)     | Allen's composition.                                                |
| [`contains`](#lacing.allen.contains)(a, b)      | Allen relation `contains`: true when `a` contains `b`.              |
| [`during`](#lacing.allen.during)(a, b)        | Allen relation `during`: true when `a` during `b`.                  |
| [`equals`](#lacing.allen.equals)(a, b)        | Allen relation `equals`: true when `a` equals `b`.                  |
| [`finished_by`](#lacing.allen.finished_by)(a, b)   | Allen relation `finished_by`: true when `a` finished by `b`.        |
| [`finishes`](#lacing.allen.finishes)(a, b)      | Allen relation `finishes`: true when `a` finishes `b`.              |
| [`intersects`](#lacing.allen.intersects)(a, b)    | True iff `a` and `b` share any positive measure of time.            |
| [`meets`](#lacing.allen.meets)(a, b)         | Allen relation `meets`: true when `a` meets `b`.                    |
| [`met_by`](#lacing.allen.met_by)(a, b)        | Allen relation `met_by`: true when `a` met by `b`.                  |
| [`overlapped_by`](#lacing.allen.overlapped_by)(a, b) | Allen relation `overlapped_by`: true when `a` overlapped by `b`.    |
| [`overlaps`](#lacing.allen.overlaps)(a, b)      | Allen relation `overlaps`: true when `a` overlaps `b`.              |
| [`relate`](#lacing.allen.relate)(a, b)        | Return the unique Allen relation between two well-formed intervals. |
| [`started_by`](#lacing.allen.started_by)(a, b)    | Allen relation `started_by`: true when `a` started by `b`.          |
| [`starts`](#lacing.allen.starts)(a, b)        | Allen relation `starts`: true when `a` starts `b`.                  |

### Classes

| [`AllenRelation`](#lacing.allen.AllenRelation)(\*values)   | The thirteen Allen relations.   |
|----------------------------------------------------------------------------|---------------------------------|

### *class* lacing.allen.AllenRelation(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

The thirteen Allen relations.

Symbols match Allen (1983); inverse pairs end in `i`.

#### inverse()

The inverse relation.

* **Return type:**
  [`AllenRelation`](#lacing.allen.AllenRelation)

### lacing.allen.PREDICATE_BY_RELATION *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[AllenRelation](#lacing.allen.AllenRelation), [Callable](https://docs.python.org/3/library/typing.html#typing.Callable)[[[TimeInterval](lacing.time.html.md#lacing.time.TimeInterval), [TimeInterval](lacing.time.html.md#lacing.time.TimeInterval)], [bool](https://docs.python.org/3/builtins/functions.html#bool)]]* *= {AllenRelation.BEFORE: <function before>, AllenRelation.EQUALS: <function equals>, AllenRelation.AFTER: <function after>, AllenRelation.DURING: <function during>, AllenRelation.CONTAINS: <function contains>, AllenRelation.FINISHES: <function finishes>, AllenRelation.FINISHED_BY: <function finished_by>, AllenRelation.MEETS: <function meets>, AllenRelation.MET_BY: <function met_by>, AllenRelation.OVERLAPS: <function overlaps>, AllenRelation.OVERLAPPED_BY: <function overlapped_by>, AllenRelation.STARTS: <function starts>, AllenRelation.STARTED_BY: <function started_by>}*

Lookup table — used by `IntervalAnnotationStore` to dispatch by relation.

### lacing.allen.after(a, b)

Allen relation `after`: true when `a` after `b`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### lacing.allen.before(a, b)

Allen relation `before`: true when `a` before `b`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### lacing.allen.compose(r1, r2)

Allen’s composition. See module docstring.

Phase 0 returns the universal set (all 13 relations) for any pair where
a unique answer is not encoded — correct but uninformative. The full
table lands in Phase 5; this function is a stable surface for callers
written against it now.

* **Return type:**
  [`set`](https://docs.python.org/3/builtins/stdtypes.html#set)[[`AllenRelation`](#lacing.allen.AllenRelation)]

### lacing.allen.contains(a, b)

Allen relation `contains`: true when `a` contains `b`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### lacing.allen.during(a, b)

Allen relation `during`: true when `a` during `b`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### lacing.allen.equals(a, b)

Allen relation `equals`: true when `a` equals `b`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### lacing.allen.finished_by(a, b)

Allen relation `finished_by`: true when `a` finished by `b`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### lacing.allen.finishes(a, b)

Allen relation `finishes`: true when `a` finishes `b`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### lacing.allen.intersects(a, b)

True iff `a` and `b` share any positive measure of time.

`meets`/`met_by` are NOT intersections (half-open boundaries share
zero measure). Two zero-length point intervals at the same instant DO
intersect (they’re equal).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### lacing.allen.meets(a, b)

Allen relation `meets`: true when `a` meets `b`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### lacing.allen.met_by(a, b)

Allen relation `met_by`: true when `a` met by `b`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### lacing.allen.overlapped_by(a, b)

Allen relation `overlapped_by`: true when `a` overlapped by `b`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### lacing.allen.overlaps(a, b)

Allen relation `overlaps`: true when `a` overlaps `b`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### lacing.allen.relate(a, b)

Return the unique Allen relation between two well-formed intervals.

Exactly one of the 13 relations holds for any pair of well-formed
(`start <= end`) intervals.

Caveat: when both `a` and `b` are point intervals (zero-length),
`meets` and `met_by` would both technically apply alongside `equals`.
We resolve that by preferring `equals` for identical intervals; the
`meets`/`met_by` predicates exclude `a == b` accordingly.

* **Return type:**
  [`AllenRelation`](#lacing.allen.AllenRelation)

### lacing.allen.started_by(a, b)

Allen relation `started_by`: true when `a` started by `b`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### lacing.allen.starts(a, b)

Allen relation `starts`: true when `a` starts `b`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)
