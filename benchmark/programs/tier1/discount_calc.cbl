      * DISCOUNT CALCULATION (tier 1)
      * Record (15 bytes): ITEM X(6) | PRICE 9(5)V99 | PCT 9(2)
      * Discount is rounded to cents; net = price - discount.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DISCCALC.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT DISC-FILE ASSIGN TO "input.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  DISC-FILE.
       01  DISC-REC.
           05 DR-ITEM        PIC X(6).
           05 DR-PRICE       PIC 9(5)V99.
           05 DR-PCT         PIC 9(2).

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG       PIC X        VALUE "N".
           88 INPUT-DONE                  VALUE "Y".
       01  WS-DISCOUNT       PIC 9(5)V99  VALUE 0.
       01  WS-NET            PIC 9(5)V99  VALUE 0.
       01  WS-TOTAL-NET      PIC 9(8)V99  VALUE 0.
       01  WS-COUNT          PIC 9(3)     VALUE 0.
       01  WS-PRICE-ED       PIC ZZ,ZZ9.99.
       01  WS-DISC-ED        PIC ZZ,ZZ9.99.
       01  WS-NET-ED         PIC ZZ,ZZ9.99.
       01  WS-TOTAL-ED       PIC ZZ,ZZZ,ZZ9.99.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT DISC-FILE
           PERFORM READ-PARA
           PERFORM PROCESS-PARA UNTIL INPUT-DONE
           CLOSE DISC-FILE
           PERFORM SUMMARY-PARA
           STOP RUN.

       READ-PARA.
           READ DISC-FILE
               AT END SET INPUT-DONE TO TRUE
           END-READ.

       PROCESS-PARA.
           COMPUTE WS-DISCOUNT ROUNDED = DR-PRICE * DR-PCT / 100
           COMPUTE WS-NET = DR-PRICE - WS-DISCOUNT
           ADD WS-NET TO WS-TOTAL-NET
           ADD 1 TO WS-COUNT
           MOVE DR-PRICE TO WS-PRICE-ED
           MOVE WS-DISCOUNT TO WS-DISC-ED
           MOVE WS-NET TO WS-NET-ED
           DISPLAY DR-ITEM " " WS-PRICE-ED " " DR-PCT "% "
               WS-DISC-ED " " WS-NET-ED
           PERFORM READ-PARA.

       SUMMARY-PARA.
           MOVE WS-TOTAL-NET TO WS-TOTAL-ED
           DISPLAY "ITEMS: " WS-COUNT " NET TOTAL: " WS-TOTAL-ED.