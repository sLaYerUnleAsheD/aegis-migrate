      * ORDER CHECK (tier 3): EVALUATE with several WHEN branches
      * Record (15 bytes): ID X(5) | STAT X | QTY 9(3) | PRICE 9(4)V99
      * N new: qty * price.  S shipped: +5 pct handling, rounded.
      * C cancelled: zero.  Anything else is invalid.  QTY 0 is a bad
      * quantity whatever the status.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDERCHK.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ORDER-FILE ASSIGN TO "input.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  ORDER-FILE.
       01  ORDER-REC.
           05 OR-ID          PIC X(5).
           05 OR-STAT        PIC X(1).
           05 OR-QTY         PIC 9(3).
           05 OR-PRICE       PIC 9(4)V99.

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG       PIC X        VALUE "N".
           88 INPUT-DONE                  VALUE "Y".
       01  WS-TOTAL          PIC 9(8)V99  VALUE 0.
       01  WS-GRAND          PIC 9(10)V99 VALUE 0.
       01  WS-NEW-COUNT      PIC 99       VALUE 0.
       01  WS-SHIP-COUNT     PIC 99       VALUE 0.
       01  WS-CANCEL-COUNT   PIC 99       VALUE 0.
       01  WS-INVALID        PIC 99       VALUE 0.
       01  WS-BAD-QTY        PIC 99       VALUE 0.
       01  WS-QTY-ED         PIC ZZ9.
       01  WS-PRICE-ED       PIC Z,ZZ9.99.
       01  WS-TOTAL-ED       PIC ZZ,ZZZ,ZZ9.99.
       01  WS-GRAND-ED       PIC Z,ZZZ,ZZZ,ZZ9.99.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT ORDER-FILE
           PERFORM READ-PARA
           PERFORM PROCESS-PARA UNTIL INPUT-DONE
           CLOSE ORDER-FILE
           PERFORM SUMMARY-PARA
           STOP RUN.

       READ-PARA.
           READ ORDER-FILE
               AT END SET INPUT-DONE TO TRUE
           END-READ.

       PROCESS-PARA.
           MOVE 0 TO WS-TOTAL
           EVALUATE TRUE
               WHEN OR-QTY = 0
                   ADD 1 TO WS-BAD-QTY
                   DISPLAY OR-ID " BAD QTY"
               WHEN OR-STAT = "N"
                   COMPUTE WS-TOTAL = OR-QTY * OR-PRICE
                   ADD 1 TO WS-NEW-COUNT
                   PERFORM SHOW-PARA
               WHEN OR-STAT = "S"
                   COMPUTE WS-TOTAL ROUNDED =
                       OR-QTY * OR-PRICE * 1.05
                   ADD 1 TO WS-SHIP-COUNT
                   PERFORM SHOW-PARA
               WHEN OR-STAT = "C"
                   ADD 1 TO WS-CANCEL-COUNT
                   PERFORM SHOW-PARA
               WHEN OTHER
                   ADD 1 TO WS-INVALID
                   DISPLAY OR-ID " BAD STATUS " OR-STAT
           END-EVALUATE
           ADD WS-TOTAL TO WS-GRAND
           PERFORM READ-PARA.

       SHOW-PARA.
           MOVE OR-QTY TO WS-QTY-ED
           MOVE OR-PRICE TO WS-PRICE-ED
           MOVE WS-TOTAL TO WS-TOTAL-ED
           DISPLAY OR-ID " " OR-STAT " " WS-QTY-ED " "
               WS-PRICE-ED " " WS-TOTAL-ED.

       SUMMARY-PARA.
           MOVE WS-GRAND TO WS-GRAND-ED
           DISPLAY "NEW: " WS-NEW-COUNT " SHIPPED: " WS-SHIP-COUNT
               " CANCELLED: " WS-CANCEL-COUNT
           DISPLAY "INVALID: " WS-INVALID " BAD QTY: " WS-BAD-QTY
           DISPLAY "GRAND TOTAL: " WS-GRAND-ED.