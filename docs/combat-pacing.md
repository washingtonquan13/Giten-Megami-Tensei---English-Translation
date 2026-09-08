# Combat pacing: why the player cannot act, and what actually schedules turns

Written 2026-09-08. The player's report was consistent across sessions: *"I was
spamming clicks on the character selector to get a turn in and couldn't, because
the enemy was too fast"*, and in the final Dantalion fight three party members
alive against one enemy produced **six enemy actions and zero party actions**.

This documents the two mechanisms behind that, both read out of the engine rather
than inferred, and records one experiment whose *null* result is now explained.

---

## 1. Turn order is a uniform random draw, with replacement

**There is no agility calculation and no initiative sort.** The turn queue is a
plain array and the scheduler fills it by drawing at random.

    0x00480AD0   the turn queue -- an array of u16 actor ids, capacity 270
    0x00480CFC   its length

    0x0042AA50   enqueue(actor, unique_flag)   append, with an optional dedupe scan
    0x0042AAA0   dequeue()                     pop the head, shift left, len--,
                                               returns 0x8000 when empty
    0x0042AA40   queue_len()

`enqueue` is a **plain FIFO append**: it scans for a duplicate only when
`unique_flag == 0`, refuses past 270 entries, and otherwise writes at `len` and
increments. Nothing sorts.

The scheduler (reached from battle sub-state 2 via `call 0x0042C740`) does this,
at `0x0042C8D6`:

    esi = 0
    while (a = dequeue()) != 0x8000:      ; drain the whole queue
        buf[esi++] = a                     ;   into a stack buffer
    ebx = esi - 1                          ; pool upper bound
    esi = di                               ; number of draws
    do:
        edx = rand_mod(ebx)                ; 0x0040B940
        enqueue(buf[edx], 1)               ; re-enqueue the drawn actor
    while (--esi)

and `0x0040B940` is exactly:

    call 0x0045B290          ; CRT rand()
    ecx = arg & 0xFF ; ecx++
    idiv ecx                 ; edx = rand() % (n + 1)
    return dx

**`ebx` is never decremented and `buf` is never modified**, so this samples *with
replacement*. One actor can be drawn several times in a single round while
another is not drawn at all. With a party of three against one enemy, a run of
six consecutive enemy actions is an ordinary outcome, not a bug in the sense of
corrupted state -- it is what the algorithm does.

This is the answer to "what schedules turns", and it is the thing to change if
combat is to be made fairer. The smallest faithful fix is **sampling without
replacement**: swap `buf[edx]` with `buf[ebx]` and decrement `ebx` after each
draw, so every actor is drawn once per round. That is a few bytes in the cave and
leaves the queue, the enqueue and everything downstream untouched.

---

## 2. An open message window disables the command UI outright

Separately from *who* acts, the player's ability to *input* is hard-gated.

The battle command UI is state 32, `0x0041D530`, and it begins:

    0x0041D530  push $0x2
    0x0041D532  call 0x00404380      ; return flag_word(0x004683F0) & 2
    0x0041D53A  test %ax,%ax
    0x0041D53D  je   0x0041D548      ; bit clear -> run the UI
    0x0041D53F  call 0x00416C20      ; bit set   -> leave; this tick does nothing
    0x0041D547  ret

`0x00404380` is `flag_word & mask`; `0x00404390` is `|= mask` and `0x004043B0` is
`&= ~mask`. Bit 1 of `0x004683F0` has **exactly one setter and one clearer in the
whole image**:

    0x0041985E   set   bit 1     (a message window opens)
    0x00419D4B   clear bit 1     (it closes)

both inside the message-window subsystem at `0x00419xxx` -- the neighbourhood the
`1E 10` page-wait handler reaches through `0x0043C0C0` -> `0x0041A930`. So while a
battle message is on screen the command UI **does not run at all**. Not a side
effect: the state handler tests that bit first and returns.

### How long a message holds the gate shut

    0x00402740   per tick: if 0x004716F8 == 0 and 0x004716F4 != 0,
                 decrement it; on reaching zero, jump to the close path
    0x00402630   set_popup_timer(n):
                     mov 0x4(%esp),%eax ; cmp $1,%ax ; jge use_it
                     mov $0xf,%eax                      <- default 15
                     mov %ax,0x004716F4

A message with no explicit duration holds the UI shut for **15 ticks -- 250 ms at
60 Hz**. Of the three callers of `set_popup_timer`, one passes `$0x3c` (60 ticks,
a full second).

**Raising this timer would make the problem worse, not better**: it lengthens the
window during which input is refused. It is the wrong lever, and it is an
inviting one, which is why it is written down here.

---

## 3. Why the battle-state divider did nothing -- a null result, explained

`7e0b76d` built `dds_dev_btl<n>.exe`, which divides the call site of the battle
state handler (state 24, `0x0042B6A0`) so the battle machine steps once every N
ticks. It had no perceptible effect and combat was provisionally written off as
"the Windows port's own balance".

**The patch was real.** Verified 2026-09-08 by reading the built exes: at
`0x0041720A`, `dds_dev.exe` calls `0x0042B6A0` while `dds_dev_btl3.exe` and
`dds_dev_btl4.exe` call the divider in the cave. So the experiment was valid and
its answer stands.

It did nothing because **it slows message production by the same factor it slows
everything else**. The binding constraint is not how fast the battle machine
steps; it is (1) that turn order is drawn at random, and (2) that the UI is shut
whenever a message is up. Dividing the whole machine leaves both ratios exactly
where they were.

---

## 4. What is not yet known

* **What `di` is** in the scheduler -- the number of draws per round. If it is
  larger than the number of combatants, that alone multiplies actions per round.
* Whether any stat feeds the draw indirectly (nothing in the drawn path reads
  one, but the *pool* is built by the nine `enqueue` sites in
  `0x0042C8xx`-`0x0042CBxx`, which have not all been read).
* Whether the command UI's own 4-way sub-state machine (`0x0041D864`) can be
  pre-empted once entered, or only refused before it starts.

## 5. Addresses, for whoever picks this up

| address | what |
|---|---|
| `0x00480AD0` | turn queue (u16 actor ids, capacity 270) |
| `0x00480CFC` | queue length |
| `0x0042AA50` | enqueue(actor, unique_flag) |
| `0x0042AAA0` | dequeue() -> actor, or `0x8000` when empty |
| `0x0042C740` | the scheduler, entered from battle sub-state 2 |
| `0x0042C8D6` | the drain-and-redraw loop |
| `0x0040B940` | `rand() % (n+1)` |
| `0x0045B290` | CRT `rand()` |
| `0x0042B6A0` | battle state handler (state 24), 9 sub-states via `0x0042C02C` |
| `0x00416BD0` / `0x00416AD0` | get_substate / set_substate(cur+1) |
| `0x0047BB72` / `0x0047BB74` | state / sub-state words |
| `0x0041D530` | battle command UI (state 32) |
| `0x004683F0` | UI flag word; **bit 1 = a message window is open** |
| `0x00404380` / `0x00404390` / `0x004043B0` | flag test / set / clear |
| `0x0041985E` / `0x00419D4B` | the only setter / clearer of bit 1 |
| `0x004716F4` / `0x004716F8` | popup countdown / its pause flag |
| `0x00402740` | per-tick countdown |
| `0x00402630` | set_popup_timer(n), default 15 ticks |
