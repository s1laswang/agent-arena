FRONTIER_SUFFIX = "\nThe day has many rounds. `end_turn` only passes one round and new tickets arrive in later rounds. After `end_turn`, call `my_tickets` again and keep working until a tool answers 'day over'. Do not stop before that.\n"
BATCH_HINT = "\nIf the tools expose list or batch operations, you may use them to save calls.\n"
SEAT_SUFFIX = FRONTIER_SUFFIX + BATCH_HINT
